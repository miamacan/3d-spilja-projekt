shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_disabled;

// G3 - površina jezera.
//
// Nema UV podataka na ovoj mreži (samo pozicija i normala), pa se sve ovdje
// računa preko svjetskih X/Z koordinata umjesto UV-a - što je i bolje za vodu.
// ALPHA ostaje na 1.0 - "prozirnost" rubova dolazi od miješanja s refrakcijom
// (vidi se dno kroz plitku vodu), ne od stvarne alfa vrijednosti.

// ---------------------------------------------------------------- površina
uniform sampler2D normal_a : filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_b : filter_linear_mipmap, repeat_enable;
uniform float tile_a = 4.0;                 // metara po pločici
uniform float tile_b = 11.0;
uniform vec2 flow_a = vec2(0.013, 0.008);   // pločica po sekundi
uniform vec2 flow_b = vec2(-0.007, 0.011);
// jezero je mirno - namjerno malo, iznad ~0.35 izgleda kao vjetrovito jezero
uniform float normal_strength : hint_range(0.0, 1.0) = 0.16;

// ---------------------------------------------------------------- boja
uniform vec3 shallow_color : source_color = vec3(0.16, 0.34, 0.30);
uniform vec3 deep_color : source_color = vec3(0.012, 0.048, 0.058);
uniform float depth_fade_distance = 2.4;    // metara do potpune "dubinske" boje
uniform float clarity_distance = 1.1;       // metara prije nego se dno izgubi
uniform vec3 shore_color : source_color = vec3(0.52, 0.70, 0.64);
uniform float shore_line_depth = 0.15;      // tanka linija ispod ove dubine
uniform float shore_strength : hint_range(0.0, 1.0) = 0.28;

// ---------------------------------------------------------------- optika
uniform float refraction : hint_range(0.0, 0.2) = 0.035;
uniform float roughness_u : hint_range(0.0, 1.0) = 0.14;
uniform float fresnel_power = 5.0;
uniform float fresnel_min : hint_range(0.0, 1.0) = 0.02;

// ---------------------------------------------------------------- valovi
// xyz = svjetska pozicija udarca, w = vrijeme početka. w <= 0 = slobodno mjesto.
// water.gd upravlja ovim nizom i prepisuje najstariji val kad se popuni.
const int MAX_RIPPLES = 16;
uniform vec4 ripples[16];
uniform int ripple_count = 0;
uniform float ripple_speed = 2.2;           // brzina širenja kruga, m/s
uniform float ripple_wavelength = 0.55;     // metara
uniform float ripple_life = 3.0;            // sekundi
uniform float ripple_amplitude : hint_range(0.0, 4.0) = 1.1;
uniform float ripple_ring_width = 1.5;      // veće = uži krug
// vlastiti "sat" za valove, postavlja ga water.gd (ne Godotov TIME) da se
// vremena ne razjednače kod pauze ili promjene brzine igre
uniform float time_now = -1.0;

uniform sampler2D depth_tex : hint_depth_texture, filter_linear_mipmap;
uniform sampler2D screen_tex : hint_screen_texture, filter_linear_mipmap;

varying vec3 v_world;

const float TAU_F = 6.283185307179586;


void vertex() {
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}


// Z komponenta normale se izračuna, ne čita iz teksture - jer se normal mape
// pod kompresijom spreme samo u 2 kanala (plavi kanal ne postoji).
vec3 unpack_normal(sampler2D t, vec2 uv) {
	vec2 xy = texture(t, uv).xy * 2.0 - 1.0;
	float z = sqrt(max(0.0, 1.0 - dot(xy, xy)));
	return vec3(xy, z);
}


// zbroji sve šireće krugove (valove) - vraća nagib normale na toj točki
vec2 ripple_tilt(vec2 p) {
	float now = time_now >= 0.0 ? time_now : TIME;
	vec2 acc = vec2(0.0);
	for (int i = 0; i < MAX_RIPPLES; i++) {
		if (i >= ripple_count) {
			break;
		}
		vec4 r = ripples[i];
		if (r.w <= 0.0) {
			continue;
		}
		float age = now - r.w;
		if (age < 0.0 || age > ripple_life) {
			continue;
		}
		vec2 d = p - r.xz;
		float dist = length(d);
		if (dist < 1e-4) {
			continue;
		}
		float radius = age * ripple_speed;
		// val postoji samo blizu širećeg ruba, ne cijelom krugu
		float band = exp(-abs(dist - radius) * ripple_ring_width);
		float t_decay = 1.0 - age / ripple_life;
		t_decay *= t_decay;
		float d_decay = 1.0 / (1.0 + dist * 0.55);
		float w = sin((dist - radius) * TAU_F / ripple_wavelength);
		acc += (d / dist) * w * band * t_decay * d_decay * ripple_amplitude;
	}
	return acc;
}


float linear_scene_depth(vec2 uv, mat4 inv_proj) {
	float raw = texture(depth_tex, uv).r;
	vec3 ndc = vec3(uv * 2.0 - 1.0, raw);
	vec4 view = inv_proj * vec4(ndc, 1.0);
	return -(view.z / view.w);
}


void fragment() {
	vec2 p = v_world.xz;

	// dvije normal-mape koje se pomiču, različite veličine i brzine
	vec3 na = unpack_normal(normal_a, p / tile_a + flow_a * TIME);
	vec3 nb = unpack_normal(normal_b, p / tile_b + flow_b * TIME);
	vec3 n_tan = normalize(na + nb);

	// ravna ploha na Y=0, pa se tangent prostor preslika izravno na svijet
	vec3 n_world = normalize(vec3(n_tan.x, n_tan.z, n_tan.y));
	n_world = normalize(mix(vec3(0.0, 1.0, 0.0), n_world, normal_strength));

	// valovi se dodaju na vrh mirne površine
	vec2 tilt = ripple_tilt(p);
	n_world = normalize(n_world + vec3(tilt.x, 0.0, tilt.y));

	// koliko je duboko ispod ovog piksela
	float scene_z = linear_scene_depth(SCREEN_UV, INV_PROJECTION_MATRIX);
	float surf_z = -VERTEX.z;
	float water_depth = max(scene_z - surf_z, 0.0);

	// refrakcija, pomaknuta prema izračunatoj normali
	vec2 ref_uv = SCREEN_UV + n_world.xz * refraction;
	// ako je pomak "pokupio" nešto ispred vode (stijenu), vrati se na
	// originalni uzorak umjesto da se kamen razmaže po površini
	float ref_scene_z = linear_scene_depth(ref_uv, INV_PROJECTION_MATRIX);
	if (ref_scene_z < surf_z) {
		ref_uv = SCREEN_UV;
	}
	vec3 behind = texture(screen_tex, ref_uv).rgb;

	// boja: tonirano po dubini, dno se gubi što je dublje
	float fade = 1.0 - exp(-water_depth / max(depth_fade_distance, 0.001));
	vec3 tint = mix(shallow_color, deep_color, fade);
	float clarity = exp(-water_depth / max(clarity_distance, 0.001));
	vec3 col = mix(tint, behind * mix(vec3(1.0), shallow_color * 1.6, 0.4), clarity);

	// tanka svjetlija linija na obali
	float shore = 1.0 - smoothstep(0.0, shore_line_depth, water_depth);
	col = mix(col, shore_color, shore * shore_strength);

	// Fresnel: pod oštrim kutom refleksija preuzima od refrakcije.
	// Stvarnu refleksiju dodaje sam Godot (ROUGHNESS/SPECULAR/NORMAL +
	// ReflectionProbe) - ovo samo spriječi da se dno vidi kroz vodu gdje
	// fizički ne bi trebalo.
	vec3 n_view = normalize((VIEW_MATRIX * vec4(n_world, 0.0)).xyz);
	float ndv = clamp(dot(n_view, normalize(VIEW)), 0.0, 1.0);
	float fres = fresnel_min + (1.0 - fresnel_min) * pow(1.0 - ndv, fresnel_power);
	col = mix(col, tint, fres * 0.6);

	ALBEDO = col;
	ALPHA = 1.0;
	METALLIC = 0.0;
	ROUGHNESS = roughness_u;
	SPECULAR = 0.5;
	NORMAL = n_view;
}
