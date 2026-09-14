# Interaktivna 3D scena špilje - Blender + Godot 4

Seminarski projekt iz kolegija **3D računalna grafika**, FPMOI Osijek.
Krečnjačka špilja s jezerom kroz koju se hoda u prvom licu, u stvarnom vremenu -
umjesto jednog gotovog, izrenderiranog kadra.

**Autori:** Mia Macan, Lovro Roguljić
**Mentor:** Domagoj Ševerdija

---

## Sadržaj

- [O projektu](#o-projektu)
- [Struktura repozitorija](#struktura-repozitorija)
- [Zahtjevi](#zahtjevi)
- [Kako pokrenuti](#kako-pokrenuti)
- [Kontrole](#kontrole)
- [Tijek rada (pipeline)](#tijek-rada-pipeline)
- [Što je gotovo, po fazama](#što-je-gotovo-po-fazama)
- [Poznata ograničenja](#poznata-ograničenja)
- [Korištenje AI alata](#korištenje-ai-alata)
- [Licenca](#licenca)

---

## O projektu

Cilj je bio napraviti prostor koji se ne gleda kroz jedan fiksan kadar, nego se
doživljava u stvarnom vremenu - hoda se kroz njega, gleda se iz bilo kojeg kuta
i fizički se djeluje na objekte u njemu (baca se kamenje u vodu, npr.).
Referentna zamisao: špilja s otvorom u stropu kroz koji dnevno svjetlo pada na
tamno jezero, stijene obrasle mahovinom i voda koja kapa niz zidove.

Projekt je podijeljen između dva alata:

- **Blender** - isključivo izrada sadržaja: geometrija, UV, bake tekstura,
  kolizijske mreže. Ništa se ne osvjetljava ovdje.
- **Godot 4** - sve što ovisi o pogledu igrača ili se mijenja tijekom
  izvođenja: osvjetljenje, magla, voda, fizika, zvuk, naknadna obrada slike.

Dvije strane komuniciraju preko jedne `glTF 2.0` (`.glb`) datoteke.

## Struktura repozitorija

```
3-dpr/                          Blender strana (izrada sadržaja)
├── blender/
│   ├── cave.blend              radni Blender fajl
│   └── tools/                  Python skripte koje generiraju/pripremaju scenu
│       ├── gen_cave.py             geometrija špilje (blockout -> high-poly)
│       ├── b4_vegetation.py        loze, paprati, Col (maska mahovine)
│       ├── b5_materials.py         spajanje materijala na image teksture
│       ├── b5_textures.py          tiling setovi (stijena, mahovina)
│       ├── b7_macro_bake.py        unique bake po-mesh macro tekstura
│       ├── matcheck.py             kontrolni renderi materijala
│       └── make_compare.py         usporedba render/referenca
├── assets/
│   ├── cave_blockout.glb       izvoz grubog modela (faza B1)
│   └── cave_env.glb            finalni izvoz cijele scene -> ide u Godot
├── textures/                   tiling setovi (base colour / normal / ORM)
└── reference/                  referentna slika i usporedbe kroz faze

3d godot dio/new-game-project/  Godot strana (scena u stvarnom vremenu)
├── project.godot                Godot 4.7 · Forward+ · Jolt Physics
├── scenes/
│   ├── main.tscn                glavna scena
│   ├── player/                  CharacterBody3D, kontrole, bacanje kamenja
│   ├── rock/                    RigidBody3D kamenčići + viewmodel
│   ├── water/                   Area3D jezero, pljuskovi, valovi
│   ├── fx/                      prašina u snopu svjetla, kapi, dim udara
│   ├── env/                     primjena shadera mahovine na uvezenu scenu
│   └── debug/                   skripte koje su izgradile i testirale scenu
│       (g2_lighting, g3_water, g4_rocks, g5_env, route_audit, ...)
├── shaders/
│   ├── water.gdshader            dubinska boja, refrakcija, Fresnel, valovi
│   ├── splash_ring.gdshader      širenje pljuska
│   └── rock_moss.gdshader        stijena + mahovina, triplanarno, po Col maski
├── assets/env/                  uvezeni cave_env.glb + njegove teksture
├── assets/textures/             mahovina, voda (generirane teksture), prašina
├── audio/                       plop, klik kamena (generirani zvukovi)
├── tools/                       Python generatori tekstura/zvuka
└── route_audit.txt              rezultat automatskog testa prohodnosti (G1)
```

## Zahtjevi

| Alat | Verzija |
|---|---|
| Blender | 5.1 / 5.2 LTS (samo za uređivanje `.blend` i pokretanje skripti iz `blender/tools/`) |
| Godot | **4.7.2**, Forward+ renderer |
| Fizika | Jolt Physics (uključen u Godot 4.7, postavljen kao projektni default) |
| GPU | Desktop kartica srednje klase - scena je budžetirana na ~16 ms/sličicu (60 fps) na 1440p |

Za samu igru **nije potreban Blender** - `cave_env.glb` je već izvezen i uvezen
u Godot projekt zajedno sa svojim teksturama.

## Kako pokrenuti

1. Instaliraj **Godot 4.7.x** (stable, standardni build).
2. Otvori Godot -> *Import* -> odaberi `3d godot dio/new-game-project/project.godot`.
3. Pusti da Godot uveze `cave_env.glb` i teksture (prvi put malo duže traje).
4. Pokreni scenu `scenes/main.tscn` (F6) ili cijeli projekt (F5).

Za uređivanje same špilje (geometrija/teksture) otvori `3-dpr/blender/cave.blend`
u Blenderu; skripte u `blender/tools/` pokreću se iznutra Blendera (Scripting
tab) i regeneriraju odgovarajući dio scene, a zatim se ponovno izvozi
`cave_env.glb` i kopira u `3d godot dio/new-game-project/assets/env/`.

## Kontrole

| Radnja | Tipka |
|---|---|
| Kretanje | `W` `A` `S` `D` |
| Trčanje | `Shift` |
| Skok | `Space` |
| Pogled | miš |
| Nišanjenje / bacanje kamena | lijevi klik miša - drži za nabijanje (0.3-1.2 s), otpusti za bacanje (6-16 m/s) |
| Prikaz/skrivanje HUD-a (pozicija, brzina, fps) | `F3` |
| Prebacivanje na referentnu kameru (`CAM_Hero`) | `H` |
| Otpusti pokazivač miša | `Esc` |

Kapa se do 30 kamenčića u sceni istovremeno; stariji se uklanjaju automatski.
Kamen koji upadne u jezero pokreće pljusak, val na površini vode i tone
sporije nego što bi padao kroz zrak.

## Tijek rada (pipeline)

1. **Blockout** u Blenderu, usklađen s referentnom fotografijom preko kamere
   `CAM_Hero` (isti kadar, isto vidno polje).
2. **Geometrija**: high-poly ljuska (voxel remesh + tri razine proceduralnog
   displacementa) -> `Decimate` -> low-poly verzija za igru; razlika u detalju
   zapečena u normal mapu. Zasebne, jako pojednostavljene kolizijske mreže
   (sufiksi `-colonly` / `-convcol`) - Godot ih pri uvozu sam pretvara u
   `StaticBody3D`/`CollisionShape3D`.
3. **Materijali**: Principled BSDF (PBR metallic/roughness), proceduralno
   izgrađen izgled zapečen u base colour / normal / ORM teksture. Maska
   mahovine je atribut boje (`Col`) po vrhu, ne tekstura.
4. **Izvoz**: `glTF 2.0` (`.glb`), +Y gore, samo kolekcije `10`-`70`
   (bez kamera, svjetala, referentnih slika).
5. **Godot**: uvezena geometrija dobiva stvarno osvjetljenje
   (`DirectionalLight3D` + `LightmapGI`), volumetrijsku maglu, `ReflectionProbe`
   za jezero, prilagođene shadere za vodu i za stijenu/mahovinu
   (triplanarno projicirana, po `Col` maski), Jolt fiziku za igrača i kamenje,
   te GPU čestice i prostorni zvuk.

Detaljno tehničko obrazloženje svake odluke (i alternative koje su
isprobane i odbačene) nalazi se u pratećem dokumentu *"Scena špilje - tehnički
pregled komponenti"* i u seminarskom radu.

## Što je gotovo, po fazama

**Blender (B0-B7):** blockout, high/low-poly ljuska, vegetacija (loze, paprati),
UV i vertex-boja maska mahovine, materijali kao image teksture (tiling set za
stijenu i mahovinu + unique "macro" bake po komadu geometrije za slojevitost i
mrlje od vode), finalni izvoz `cave_env.glb`.

**Godot (G1-G5):**

| Faza | Sadržaj |
|---|---|
| G1 | Igrač, kretanje, kamera, spawn na markeru, automatski test prohodnosti |
| G2 | Osvjetljenje, magla, `WorldEnvironment` (AgX, SSAO/SSIL, volumetrijska magla) |
| G3 | Voda - shader, pljuskovi, valovi |
| G4 | Bacanje kamenja - nabijanje, RigidBody3D, viewmodel, zvuk udarca |
| G5 | Shader mahovine, atlas lišća, prašina u snopu svjetla, kapi s loza |

`route_audit.txt` sadrži izvještaj automatiziranog testa koji provjerava da
je cijela špilja doista prohodna capsule-kolajderom igrača.

## Poznata ograničenja

Iskreno, nekoliko stvari je ostalo nedovršeno ili je svjesno odgođeno:

- **LightmapGI nije zapečen** u zadnjoj verziji - postavke su spremne, ali
  bake nije pokrenut, tako da neizravno svjetlo trenutno koristi privremene
  vrijednosti.
- **Slojevitost stijene (stratifikacija)** vidljiva u referenci djelomično
  nedostaje bez zapečenih "macro" mapa na svim komadima geometrije.
- **Mahovina čita se tamnije** nego u referenci - dio je razlike u nijansi
  posljedica toga što lightmap bake nije pokrenut; postoji i ručni
  `moss_tint` parametar u shaderu za brzu korekciju.
- **Lišće na lozama nema njihanje** (vertex sway) - namjerno izostavljeno,
  jer bi tražilo prijelaz s `StandardMaterial3D` na prilagođeni shader.
- **Kamenje se ne može pokupiti s tla** - bilo je zamišljeno kao "stretch
  goal", nije rađeno.
- **Viewmodel kamena ulazi u geometriju** kad se igrač približi zidu (nema
  posebnog render sloja za viewmodel).
- Manji propust u koherentnosti mreže (pod jezera lokalno "prореžе" kroz
  ljusku na nekoliko mjesta) - pod vodom vizualno gotovo neprimjetno.

Ništa od ovoga ne utječe na to da se scena može prohodati i doživjeti u
stvarnom vremenu; radi se o poliranju koje bi bilo sljedeće na redu.

## Korištenje AI alata

Uz Blender i Godot, u određenim fazama rada korišten je AI alat (Claude) - za
generiranje ideja i brzu provjeru pristupa, pomoć pri pisanju i ispravljanju
GDScript i Python skripti (npr. shaderi, generiranje geometrije/tekstura,
kontroler igrača) te pri organizaciji i formuliranju pratećih tekstova
(seminarski rad, ova dokumentacija). Sve finalne odluke o izgledu i
funkcionalnosti scene donesene su i provjerene od strane autora.

## Licenca

Projekt je izrađen u sklopu kolegija 3D računalna grafika (FPMOI Osijek) u
obrazovne svrhe. 3D model ribarskog broda i zvučni efekti (ako se koriste u
popratnim materijalima) preuzeti su s Fab.com / Pixabay pod njihovim uvjetima
licenciranja - vidi seminarski rad za potpune izvore.
