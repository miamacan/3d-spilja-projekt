shader_type spatial;
render_mode blend_add, unshaded, cull_disabled, depth_draw_never, shadows_disabled;

// G3 - šireći krug (val) koji udarac ostavi na površini vode.
//
// Quad se NE skalira. Izgrađen je jednom u punoj konačnoj veličini, a krug
// se crta na radijusu `progress` unutar njega. Da se umjesto toga skalirao
// sam objekt, debljina linije kruga bi se skalirala s njim - izgledalo bi
// kao debela mrlja koja se stanjuje dok raste, ne kao pravi val.
//
// depth_draw_never + blend_add da se preklapajući valovi od više kamenova
// zbrajaju umjesto da se "bore" oko dubine, i da val nikad ne zakloni vodu ispod.

uniform vec4 ring_color : source_color = vec4(0.62, 0.82, 0.78, 1.0);
uniform float progress : hint_range(0.0, 1.0) = 0.0;
uniform float thickness : hint_range(0.01, 0.5) = 0.16;
uniform float inner_fill : hint_range(0.0, 1.0) = 0.12;

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float r = length(c);

	// sam šireći krug
	float ring = 1.0 - smoothstep(0.0, thickness, abs(r - progress));

	// blaga uzburkana ploha unutar kruga, da prvi kadrovi izgledaju kao
	// stvaran poremećaj vode, ne kao krug koji se odjednom pojavi
	float fill = (1.0 - smoothstep(0.0, progress + 0.001, r)) * inner_fill
		* (1.0 - progress);

	// nestaje kroz vrijeme trajanja, i tvrdo odsječeno na rub quada
	// da se rubovi/kutovi nikad ne vide
	float life = 1.0 - progress;
	float a = (ring + fill) * life * ring_color.a * step(r, 1.0);

	ALBEDO = ring_color.rgb;
	ALPHA = clamp(a, 0.0, 1.0);
}
