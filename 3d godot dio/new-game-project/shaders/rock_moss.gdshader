shader_type spatial;
// NEPROZIRAN (opaque). Ne dodavati blend_* mod ovdje.
//
// Ako se doda prozirnost, mreže prestanu pisati dubinu, pa volumetrijska
// magla prestane biti zaklonjena zidovima špilje i "prosine" kroz njih -
// cijela slika postane svjetlija, uključujući sjene.
//
// cull_disabled, NE cull_back. Svi limestone materijali u cave_env.glb su
// dvostrani, jer je ljuska jednostrana mrežasta površina čije normale gledaju
// prema unutra. Sa cull_back bi ljuska nestala iz shadow mape kad se gleda
// izvana (baš odakle dolazi sunce), i usmjereno svjetlo bi tada osvijetlilo
// maglu kroz cijelu komoru.
render_mode cull_disabled;

// G5 - vapnenac s mahovinom koja raste na njemu.
//
// Slog stijene je nepromijenjen, postojeći zapečeni izgled (albedo, normal,
// ORM/macro mapa) iz glTF uvoza, čitan preko UV-a.
//
// Slog mahovine je T_Moss, triplanarno projiciran u svjetskom prostoru (po
// moss_tile metrima) - ne koristi UV stijene, pa se ne rasteže na kosim
// stranama gdje bi zajednički UV to učinio.
//
// Miješanje dva sloja ide po COLOR.r - to je "Col" atribut koji je Blender
// zapisao po vrhu mreže (koliko treba mahovine na tom mjestu).
//
// Prag miješanja je razlomljen šumom u svjetskom prostoru, umjesto da je
// glatki prijelaz - jer glatki prijelaz izgleda kao "pola-mahovina" mrlja
// koja u prirodi ne postoji. Mahovina ima rub, samo je rub neravan.

// ------------------------------------------------------------------ stijena
uniform sampler2D rock_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_normal : filter_linear_mipmap, repeat_enable;
// R = AO, G = roughness, B = metalnost - to su podaci, ne boja (nije source_color)
uniform sampler2D rock_orm : filter_linear_mipmap, repeat_enable;

// ------------------------------------------------------------------ mahovina
uniform sampler2D moss_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D moss_normal : filter_linear_mipmap, repeat_enable;
uniform sampler2D moss_orm : filter_linear_mipmap, repeat_enable;
uniform float moss_tile = 0.5;                  // metara po pločici
uniform vec3 moss_tint : source_color = vec3(1.0, 1.0, 1.0);
uniform float moss_roughness : hint_range(0.0, 1.0) = 0.9;
uniform float moss_normal_strength : hint_range(0.0, 2.0) = 1.0;

// ------------------------------------------------------------------ maska
uniform float mask_gain : hint_range(0.0, 4.0) = 1.0;
uniform float mask_threshold : hint_range(0.0, 1.0) = 0.22;
uniform float edge_softness : hint_range(0.001, 0.5) = 0.08;
uniform float edge_noise_scale = 1.8;           // ciklusa po metru
uniform float edge_noise_amount : hint_range(0.0, 1.0) = 0.30;
// dijagnostika: 1.0 prikaže samo masku (magenta/crno), da se provjeri
// bez potrebe za gledanjem osvijetljenog rendera
uniform float debug_mask : hint_range(0.0, 1.0) = 0.0;

varying vec3 v_world;
varying float v_mask;


float hash13(vec3 p) {
	p = fract(p * 0.1031);
	p += dot(p, p.zyx + 31.32);
	return fract((p.x + p.y) * p.z);
}

float vnoise(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float n000 = hash13(i + vec3(0.0, 0.0, 0.0));
	float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
	float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
	float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
	float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
	float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
	float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
	float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
	float x00 = mix(n000, n100, f.x);
	float x10 = mix(n010, n110, f.x);
	float x01 = mix(n001, n101, f.x);
	float x11 = mix(n011, n111, f.x);
	return mix(mix(x00, x10, f.y), mix(x01, x11, f.y), f.z);
}

// isto kao u water.gdshader - plavi kanal se izračuna, ne čita (kompresija ga briše)
vec3 unpack_n(vec4 t) {
	vec2 xy = t.xy * 2.0 - 1.0;
	return vec3(xy, sqrt(max(0.0, 1.0 - dot(xy, xy))));
}

vec3 tri_weights(vec3 n) {
	vec3 w = pow(abs(n), vec3(4.0));
	return w / max(w.x + w.y + w.z, 1e-5);
}

vec3 tri_color(sampler2D t, vec3 wp, vec3 w, float s) {
	return texture(t, wp.zy / s).rgb * w.x
		 + texture(t, wp.xz / s).rgb * w.y
		 + texture(t, wp.xy / s).rgb * w.z;
}

vec3 tri_normal(sampler2D t, vec3 wp, vec3 w, float s) {
	return normalize(unpack_n(texture(t, wp.zy / s)) * w.x
		+ unpack_n(texture(t, wp.xz / s)) * w.y
		+ unpack_n(texture(t, wp.xy / s)) * w.z);
}


void vertex() {
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_mask = COLOR.r;
}


void fragment() {
	// --- stijena, točno kako je i uvezena
	vec3 r_alb = texture(rock_albedo, UV).rgb;
	vec3 r_nrm = unpack_n(texture(rock_normal, UV));
	vec3 r_orm = texture(rock_orm, UV).rgb;

	// --- mahovina, triplanarno u svjetskom prostoru
	vec3 wn = normalize(NORMAL);
	vec3 w = tri_weights(normalize((INV_VIEW_MATRIX * vec4(wn, 0.0)).xyz));
	vec3 m_alb = tri_color(moss_albedo, v_world, w, moss_tile) * moss_tint;
	vec3 m_nrm = tri_normal(moss_normal, v_world, w, moss_tile);
	m_nrm = normalize(mix(vec3(0.0, 0.0, 1.0), m_nrm, moss_normal_strength));
	vec3 m_orm = tri_color(moss_orm, v_world, w, moss_tile);

	// --- neravni rub mahovine
	float n = vnoise(v_world * edge_noise_scale) * 0.68
			+ vnoise(v_world * edge_noise_scale * 3.7) * 0.32;
	float m = clamp(v_mask * mask_gain, 0.0, 1.0);
	float drive = m - (n - 0.5) * edge_noise_amount;
	float blend = smoothstep(mask_threshold - edge_softness,
							 mask_threshold + edge_softness, drive);

	if (debug_mask > 0.5) {
		ALBEDO = vec3(blend, blend * 0.25, blend * 0.75);
		ROUGHNESS = 1.0;
		METALLIC = 0.0;
		SPECULAR = 0.0;
		NORMAL_MAP = vec3(0.5, 0.5, 1.0);
		AO = 1.0;
	} else {
		ALBEDO = mix(r_alb, m_alb, blend);
		NORMAL_MAP = normalize(mix(r_nrm, m_nrm, blend)) * 0.5 + 0.5;
		NORMAL_MAP_DEPTH = 1.0;
		// moss_roughness je ciljna vrijednost, ORM mahovine je samo modulira
		float m_rough = clamp(moss_roughness * (0.75 + 0.5 * m_orm.g), 0.0, 1.0);
		ROUGHNESS = mix(r_orm.g, m_rough, blend);
		METALLIC = 0.0;
		// R kanal (AO) je slobodan za korištenje ovdje - StandardMaterial3D
		// ga pri uvozu nije spajao nigdje
		AO = mix(r_orm.r, m_orm.r, blend);
		AO_LIGHT_AFFECT = 0.35;
	}
}
