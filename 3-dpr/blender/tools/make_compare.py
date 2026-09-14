# Generira sliku za usporedbu: referentna fotografija vs. naš render iz Blendera.
# Gore su dvije slike jedna pored druge, dolje je 50/50 preklop (blend) s oznakama
# ključnih visina (Z koordinata) da se vidi poklapaju li se proporcije.

from PIL import Image, ImageDraw, ImageFont

REF = "/root/.claude/uploads/abd68b5b-5931-5f7c-9f9b-401f2d01a2b6/855debff-image.png"
RND = "/mnt/user-data/uploads/3-dpr/blender/_src/_b1_hero.png"
OUT = "/mnt/user-data/outputs/b1_hero_compare.png"

f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
fb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 23)

# dimenzije platna
PW, PH = 952, 535
GAP, LAB = 12, 34
W = PW * 2 + GAP * 3
BH = W - GAP * 2
BHh = round(BH * 1080 / 1920)
H = LAB + PH + GAP * 2 + LAB + BHh + GAP

canvas = Image.new("RGB", (W, H), (24, 24, 26))
d = ImageDraw.Draw(canvas, "RGBA")

ref = Image.open(REF).convert("RGB")
rnd = Image.open(RND).convert("RGB")

# gornji red: referenca lijevo, naš render desno, s vodoravnom linijom i točkom za usporedbu
for i, (im, title) in enumerate(((ref, "REFERENCE"),
                                 (rnd, "B1 BLOCKOUT  —  CAM_Hero, Workbench"))):
    x = GAP + i * (PW + GAP)
    d.text((x, 8), title, font=fb, fill=(235, 235, 235))
    canvas.paste(im.resize((PW, PH), Image.LANCZOS), (x, LAB))
    d.line([(x, LAB + 0.3823 * PH), (x + PW, LAB + 0.3823 * PH)],
           fill=(80, 220, 255, 150), width=1)
    sx, sy = x + 0.3429 * PW, LAB + 0.5992 * PH
    d.ellipse([sx - 11, sy - 11, sx + 11, sy + 11], outline=(255, 90, 200), width=3)
    d.rectangle([x, LAB, x + PW - 1, LAB + PH - 1], outline=(90, 90, 95), width=1)

# donji dio: 50/50 preklop dviju slika, s oznakama visina
by = LAB + PH + GAP * 2
d.text((GAP, by - 26), "50/50 BLEND  —  cyan = optical horizon,  "
                       "magenta = LEDGE stage top as CAM_Hero projects it",
       font=fb, fill=(235, 235, 235))
blend = Image.blend(ref.resize((BH, BHh), Image.LANCZOS),
                    rnd.resize((BH, BHh), Image.LANCZOS), 0.5)
canvas.paste(blend, (GAP, by))

bd = ImageDraw.Draw(canvas, "RGBA")


def gl(vfrac, col, text):
    # iscrtava isprekidanu vodoravnu liniju s oznakom (labelom) na zadanoj visini
    y = by + vfrac * BHh
    xx = GAP
    while xx < GAP + BH:
        bd.line([(xx, y), (min(xx + 16, GAP + BH), y)], fill=col, width=2)
        xx += 30
    bb = bd.textbbox((GAP + 14, y - 28), text, font=f)
    bd.rectangle([bb[0] - 6, bb[1] - 4, bb[2] + 6, bb[3] + 4], fill=(0, 0, 0, 180))
    bd.text((GAP + 14, y - 28), text, font=f, fill=col)


gl(0.3823, (80, 220, 255), "optical horizon  Z = +7.20 m")
gl(0.7098, (255, 215, 60), "water plane Z = 0  at 25 m")
gl(0.9544, (255, 215, 60), "water plane Z = 0  at 14 m")

sx, sy = GAP + 0.3429 * BH, by + 0.5992 * BHh
bd.ellipse([sx - 16, sy - 16, sx + 16, sy + 16], outline=(255, 90, 200), width=4)
bd.text((sx + 28, sy - 11), "stage top  Z = +5.50 m", font=f, fill=(255, 90, 200))
bd.rectangle([GAP, by, GAP + BH - 1, by + BHh - 1], outline=(90, 90, 95), width=1)

canvas.save(OUT)
print("ok", canvas.size)
