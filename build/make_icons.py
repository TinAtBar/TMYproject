"""Erzeugt alle Icons aus dem Firmenlogo build/icons/barlage-quelle.ico (Pillow nötig).

Ausgabe:
  build/icons/barlagepm.ico, barlagepm-admin.ico   (exe, Installer, Fenster)
  web/icons/icon-180.png (apple-touch), icon-192.png, icon-512.png, icon-maskable-512.png,
  web/icons/favicon.ico, web/icons/logo.png        (Logo in Seitenleiste/Anmeldung)
Die Quelle hat schwarze statt transparente Ecken → Maske mit abgerundetem Quadrat (Radius 36/256).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "build" / "icons" / "barlage-quelle.ico"
OUT = ROOT / "build" / "icons"
WEB = ROOT / "web" / "icons"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
NAVY = (3, 45, 110, 255)
RADIUS = 36 / 256


def master():
    from PIL import Image, ImageDraw
    im = Image.open(SRC)
    im.size = (256, 256)
    im = im.convert("RGBA")
    big = 1024
    maske = Image.new("L", (big, big), 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(RADIUS * big), fill=255)
    im.putalpha(maske.resize((256, 256), Image.LANCZOS))
    return im


def flach(im, groesse, rand=0.0):
    """Logo auf weißem, vollflächigem Quadrat (für apple-touch / maskable)."""
    from PIL import Image
    bg = Image.new("RGBA", (groesse, groesse), (255, 255, 255, 255))
    inner = int(groesse * (1 - 2 * rand))
    logo = im.resize((inner, inner), Image.LANCZOS)
    bg.alpha_composite(logo, ((groesse - inner) // 2, (groesse - inner) // 2))
    return bg.convert("RGB")


def admin_variante(im):
    from PIL import ImageDraw
    adm = im.copy()
    d = ImageDraw.Draw(adm)
    w = adm.width
    r = w // 5
    cx = cy = w - r - w // 24
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=NAVY, outline=(255, 255, 255, 255), width=w // 48)
    d.ellipse((cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2), outline=(255, 255, 255, 255), width=w // 32)
    return adm


def main():
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    im = master()
    im.save(OUT / "barlagepm.ico", sizes=SIZES)
    admin_variante(im).save(OUT / "barlagepm-admin.ico", sizes=SIZES)
    flach(im, 180).save(WEB / "icon-180.png")
    im.resize((192, 192), Image.LANCZOS).save(WEB / "icon-192.png")
    im.resize((512, 512), Image.LANCZOS).save(WEB / "icon-512.png")
    flach(im, 512, rand=0.1).save(WEB / "icon-maskable-512.png")
    im.resize((128, 128), Image.LANCZOS).save(WEB / "logo.png")
    im.save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("Icons erzeugt in", OUT, "und", WEB)


if __name__ == "__main__":
    main()
