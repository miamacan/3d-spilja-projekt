shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_disabled;

// G3 — the pool surface.
//
// NOTE ON UVs: WATER_Pool_Surface comes out of cave_env.glb with only POSITION
// and NORMAL -- no TEXCOORD_0 and no TANGENT. Everything here is therefore
// driven by WORLD XZ rather than UV, which is what you want for water anyway,
// and the tangent frame is built by hand from the fact that the surface is a
// flat horizontal plane at Y = 0. Do not add a NORMAL_MAP assignment; without
// tangents it would come out wrong.
//
// ALPHA stays 1.0. The "near-transparent at the edges" the brief asks for is
// produced by the refraction/clarity mix showing the pool bed through shallow
// water, not by literal alpha -- doing both double-counts and the shallows go
// muddy.

// ---------------------------------------------------------------- surface
uniform sampler2D normal_a : filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_b : filter_linear_mipmap, repeat_enable;
uniform float tile_a = 4.0;                 // metres per tile
uniform float tile_b = 11.0;
uniform vec2 flow_a = vec2(0.013, 0.008);   // tiles per second
uniform vec2 flow_b = vec2(-0.007, 0.011);
// The pool is still: this is deliberately small. Above ~0.35 it reads as a
// windy lake rather than standing cave water.
uniform float normal_strength : hint_range(0.0, 1.0) = 0.16;

// ---------------------------------------------------------------- colour
uniform vec3 shallow_color : source_color = vec3(0.16, 0.34, 0.30);
uniform vec3 deep_color : source_color = vec3(0.012, 0.048, 0.058);
uniform float depth_fade_distance = 2.4;    // metres to reach deep_color
uniform float clarity_distance = 1.1;       // metres before the bed is lost
uniform vec3 shore_color : source_color = vec3(0.52, 0.70, 0.64);
uniform float shore_line_depth = 0.15;      // brief: a thin line under 0.15 m
uniform float shore_strength : hint_range(0.0, 1.0) = 0.28;

// ---------------------------------------------------------------- optics
uniform float refraction : hint_range(0.0, 0.2) = 0.035;
uniform float roughness_u : hint_range(0.0, 1.0) = 0.14;
uniform float fresnel_power = 5.0;
uniform float fresnel_min : hint_range(0.0, 1.0) = 0.02;

// ---------------------------------------------------------------- ripples
// xyz = world impact position, w = start time (from TIME at the moment of the
// hit). w <= 0 means the slot is empty. water.gd owns this array and overwrites
// the oldest slot when it runs out.
const int MAX_RIPPLES = 16;
uniform vec4 ripples[16];
uniform int ripple_count = 0;
uniform float ripple_speed = 2.2;           // ring expansion, m/s
uniform float ripple_wavelength = 0.55;     // metres
uniform float ripple_life = 3.0;            // seconds
uniform float ripple_amplitude : hint_range(0.0, 4.0) = 1.1;
uniform float ripple_ring_width = 1.5;      // higher = tighter ring
// The ripple clock. water.gd writes both this AND each ripple's start time from
// the same accumulator, so the two cannot drift. Using the shader's own TIME for
// the start stamps would mean comparing against Time.get_ticks_msec(), which is
// a DIFFERENT clock with a different origin -- close enough to look right and
// wrong enough to misbehave under pause or a changed time_scale.
// Falls back to TIME if nothing ever sets it, so a missing script degrades to
// slightly-off ripples rather than to no ripples at all.
uniform float time_now = -1.0;

uniform sampler2D depth_tex : hint_depth_texture, filter_linear_mipmap;
uniform sampler2D screen_tex : hint_screen_texture, filter_linear_mipmap;

varying vec3 v_world;

const float TAU_F = 6.283185307179586;


void vertex() {
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}


// Reconstruct Z rather than reading blue: the maps import as normal maps, so
// under VRAM compression they become two-channel (RGTC) and blue is gone.
vec3 unpack_normal(sampler2D t, vec2 uv) {
	vec2 xy = texture(t, uv).xy * 2.0 - 1.0;
	float z = sqrt(max(0.0, 1.0 - dot(xy, xy)));
	return vec3(xy, z);
}


// Expanding rings, summed. Returns a world-space XZ tilt to add to the normal.
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
		// a travelling ring: the wave only exists near the expanding front
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

	// --- two scrolling normal maps at different scales and speeds
	vec3 na = unpack_normal(normal_a, p / tile_a + flow_a * TIME);
	vec3 nb = unpack_normal(normal_b, p / tile_b + flow_b * TIME);
	vec3 n_tan = normalize(na + nb);

	// Flat plane at Y = 0, so tangent space maps straight onto world:
	// tangent X -> world X, tangent Y -> world Z, tangent Z -> world Y.
	vec3 n_world = normalize(vec3(n_tan.x, n_tan.z, n_tan.y));
	n_world = normalize(mix(vec3(0.0, 1.0, 0.0), n_world, normal_strength));

	// --- ripples ride on top of the ambient surface
	vec2 tilt = ripple_tilt(p);
	n_world = normalize(n_world + vec3(tilt.x, 0.0, tilt.y));

	// --- how deep is the water under this pixel
	float scene_z = linear_scene_depth(SCREEN_UV, INV_PROJECTION_MATRIX);
	float surf_z = -VERTEX.z;
	float water_depth = max(scene_z - surf_z, 0.0);

	// --- refraction, offset by the perturbed normal
	vec2 ref_uv = SCREEN_UV + n_world.xz * refraction;
	// A naive offset can pick up geometry standing IN FRONT of the water (the
	// outcrop, a boulder), smearing rock across the surface. If the sample is
	// nearer than the water, fall back to the unoffset one.
	float ref_scene_z = linear_scene_depth(ref_uv, INV_PROJECTION_MATRIX);
	if (ref_scene_z < surf_z) {
		ref_uv = SCREEN_UV;
	}
	vec3 behind = texture(screen_tex, ref_uv).rgb;

	// --- colour: tint by depth, and lose the bed as it gets deeper
	float fade = 1.0 - exp(-water_depth / max(depth_fade_distance, 0.001));
	vec3 tint = mix(shallow_color, deep_color, fade);
	float clarity = exp(-water_depth / max(clarity_distance, 0.001));
	vec3 col = mix(tint, behind * mix(vec3(1.0), shallow_color * 1.6, 0.4), clarity);

	// --- the thin lighter shoreline
	float shore = 1.0 - smoothstep(0.0, shore_line_depth, water_depth);
	col = mix(col, shore_color, shore * shore_strength);

	// --- Fresnel: at grazing angles reflection takes over from refraction.
	// The engine adds the actual reflection via ROUGHNESS/SPECULAR/NORMAL and
	// the ReflectionProbe over the chamber; this just stops the refracted bed
	// from showing through where it physically would not.
	//
	// Uses the PERTURBED normal, converted here rather than read back from
	// NORMAL -- NORMAL still holds the flat interpolated plane normal at this
	// point, so reading it would make the ripples invisible to the Fresnel term.
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
