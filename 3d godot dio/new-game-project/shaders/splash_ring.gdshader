shader_type spatial;
render_mode blend_add, unshaded, cull_disabled, depth_draw_never, shadows_disabled;

// G3 — the expanding ring left on the surface by an impact.
//
// The quad does NOT scale. It is built once at the full final diameter and the
// ring is drawn at radius `progress` inside it. Scaling the node instead means
// the ring's line thickness scales with it, so it starts as a thick blob and
// thins as it grows, which reads as a shockwave rather than a water ripple.
//
// depth_draw_never + blend_add so overlapping rings from several rocks add
// rather than z-fight, and so the ring never occludes the water under it.

uniform vec4 ring_color : source_color = vec4(0.62, 0.82, 0.78, 1.0);
uniform float progress : hint_range(0.0, 1.0) = 0.0;
uniform float thickness : hint_range(0.01, 0.5) = 0.16;
uniform float inner_fill : hint_range(0.0, 1.0) = 0.12;

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float r = length(c);

	// the travelling ring
	float ring = 1.0 - smoothstep(0.0, thickness, abs(r - progress));

	// a faint disturbed disc inside it, so the very first frames read as a
	// surface break rather than a bare circle appearing from nowhere
	float fill = (1.0 - smoothstep(0.0, progress + 0.001, r)) * inner_fill
		* (1.0 - progress);

	// fade out over the life, and hard-clip to the quad's inscribed circle so
	// the corners never show
	float life = 1.0 - progress;
	float a = (ring + fill) * life * ring_color.a * step(r, 1.0);

	ALBEDO = ring_color.rgb;
	ALPHA = clamp(a, 0.0, 1.0);
}
