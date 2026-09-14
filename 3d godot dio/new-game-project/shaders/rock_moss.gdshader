shader_type spatial;
// OPAQUE. Do not add a blend_* mode here.
//
// This started as `blend_mix, depth_draw_opaque`, copied from water.gdshader
// where it belongs. On rock it stopped the meshes writing depth, so the
// volumetric fog was no longer occluded by the cave walls and integrated
// straight through them: every pixel in the frame got brighter, including ones
// that were pure shadow, and mean luminance went 0.117 -> 0.590. Measured by
// rendering the same frame with material_override cleared and differencing.
//
// cull_disabled, NOT cull_back. Every limestone material in cave_env.glb is
// double-sided (cull_mode 2), because the shell is a one-sided marched surface
// whose normals face into the chamber. With cull_back the shell has no
// front faces when seen from OUTSIDE -- which is exactly where the sun is -- so
// it dropped out of the shadow map entirely and the directional light lit the
// volumetric fog through the whole chamber. The fog region of the hero frame
// went 0.273 -> 0.827 mean luminance and stayed there even with ALBEDO forced
// to black, which is what pinned it on shadows rather than on the material.
render_mode cull_disabled;

// G5 — limestone with moss growing on it.
//
// The rock layer is the EXISTING baked look, unchanged: the same albedo, normal
// and per-mesh ORM/macro map the glTF import already wired up, sampled by UV.
// UVTile carries the 2 m-per-unit tiling in the mesh itself, so uv1_scale is 1
// and this samples UV straight.
//
// The moss layer is T_Moss, triplanar in WORLD space at moss_tile metres, so it
// does not inherit the rock's UV layout and does not stretch on the steep faces
// where a shared unwrap would.
//
// The blend is COLOR.r -- the `Col` attribute Blender wrote, which arrives as
// COLOR_0. Measured in the imported meshes:
//     ENT_Ground 0.748 mean, LEDGE_Outcrop 0.195, ENT_Tunnel 0.269,
//     boulders 0.14-0.35, CAVE_Shell_Main 0.051, ROCK_01_01 exactly 0.
// Those are whole-mesh means over very uneven masks; the Blender handoff's
// per-zone figures are what the defaults below are tuned against -- upward
// faces 0.464, left wall 0.142, right wall 0.023, wet band and underwater 0.000.
//
// The threshold is broken by world-space noise rather than used as a straight
// mix, because a straight mix of two textures by a smooth mask reads as a
// cross-fade -- a gradient of "half mossy rock" that exists nowhere in nature.
// Moss has an edge; it just has a ragged one.

// ------------------------------------------------------------------ rock
uniform sampler2D rock_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_normal : filter_linear_mipmap, repeat_enable;
// R = AO, G = roughness, B = metallic. NOT source_color: it is data, not colour.
uniform sampler2D rock_orm : filter_linear_mipmap, repeat_enable;

// ------------------------------------------------------------------ moss
uniform sampler2D moss_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D moss_normal : filter_linear_mipmap, repeat_enable;
uniform sampler2D moss_orm : filter_linear_mipmap, repeat_enable;
uniform float moss_tile = 0.5;                  // metres per tile (handoff: 0.5)
uniform vec3 moss_tint : source_color = vec3(1.0, 1.0, 1.0);
uniform float moss_roughness : hint_range(0.0, 1.0) = 0.9;
uniform float moss_normal_strength : hint_range(0.0, 2.0) = 1.0;

// ------------------------------------------------------------------ mask
uniform float mask_gain : hint_range(0.0, 4.0) = 1.0;
uniform float mask_threshold : hint_range(0.0, 1.0) = 0.22;
uniform float edge_softness : hint_range(0.001, 0.5) = 0.08;
uniform float edge_noise_scale = 1.8;           // cycles per metre
uniform float edge_noise_amount : hint_range(0.0, 1.0) = 0.30;
// Debug: 1.0 shows the final blend as flat magenta-on-black so the mask can be
// checked against Blender's numbers without guessing from a lit render.
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

// Blue is reconstructed rather than read: under RGTC these maps are two-channel
// and blue is simply gone. Same reason as water.gdshader.
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
	// --- rock, exactly as the import had it
	vec3 r_alb = texture(rock_albedo, UV).rgb;
	vec3 r_nrm = unpack_n(texture(rock_normal, UV));
	vec3 r_orm = texture(rock_orm, UV).rgb;

	// --- moss, triplanar in world space
	vec3 wn = normalize(NORMAL);
	vec3 w = tri_weights(normalize((INV_VIEW_MATRIX * vec4(wn, 0.0)).xyz));
	vec3 m_alb = tri_color(moss_albedo, v_world, w, moss_tile) * moss_tint;
	vec3 m_nrm = tri_normal(moss_normal, v_world, w, moss_tile);
	m_nrm = normalize(mix(vec3(0.0, 0.0, 1.0), m_nrm, moss_normal_strength));
	vec3 m_orm = tri_color(moss_orm, v_world, w, moss_tile);

	// --- the ragged edge
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
		// moss_roughness is the target (~0.9); the moss ORM only modulates it
		float m_rough = clamp(moss_roughness * (0.75 + 0.5 * m_orm.g), 0.0, 1.0);
		ROUGHNESS = mix(r_orm.g, m_rough, blend);
		METALLIC = 0.0;
		// The glTF import left the ORM's R channel (AO) unconnected because
		// StandardMaterial3D only took it as roughness. Here it is free to use.
		AO = mix(r_orm.r, m_orm.r, blend);
		AO_LIGHT_AFFECT = 0.35;
	}
}
