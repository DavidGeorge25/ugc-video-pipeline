"""Batch 2 sent-inbox screens (monogram badges, varied subjects/openers per Hedwig brief)."""
import sys
sys.path.insert(0, ".")
import emails_bg as E
from PIL import Image, ImageDraw
P = {
 "scooter": ("E-Scooter", "e-scooter", ["Segway-Ninebot","NIU","Apollo","Gotrax","Hiboy","Varla","Unagi","Kaabo","Dualtron","Inokim","Xiaomi","Pure Electric","Hover-1","Razor","EMOVE","Fluid Freeride","Okai","Turboant","Splach","Mearth"]),
 "pc": ("Gaming PC", "gaming PC", ["Alienware","Corsair","NZXT","MSI","ASUS ROG","Origin PC","CyberPowerPC","iBuyPower","Maingear","HP Omen","Lenovo Legion","Acer Predator","Skytech","Falcon Northwest","Digital Storm","Xidax","Starforge","Lian Li","Razer","Velztorm"]),
 "drone": ("Drone", "drone", ["DJI","Autel Robotics","Skydio","Parrot","Holy Stone","Potensic","Ryze Tello","Snaptain","Hubsan","Yuneec","Zino","Bwine","Ruko","Sanrock","FIMI","Syma","Contixo","Walkera","DroneX","Exo Drones"]),
 "headphones": ("Headphones", "headphones", ["Sony","Bose","Apple","Sennheiser","Beats","JBL","Bang & Olufsen","Audio-Technica","Shure","Skullcandy","Marshall","Jabra","AKG","Soundcore","Focal","Master & Dynamic","Beyerdynamic","Philips","Razer","Nothing"]),
 "sneakers": ("Sneaker", "sneakers", ["Nike","Adidas","New Balance","Puma","Reebok","Asics","Converse","Vans","Jordan","Hoka","On Running","Saucony","Brooks","Under Armour","Salomon","Skechers","Fila","Mizuno","Veja","Allbirds"]),
}
SUBJ = ["{P} Review Request", "{P} Collaboration", "Creator Partnership", "{P} Review Unit", "{P} Seeding Request",
        "Content Collaboration", "Demo {P} Request", "Creator {P} Request", "{P} Collab Inquiry"]
OPEN = ["I'd love to test your newest {p} for a video", "I'm reaching out about a review unit for my channel",
        "would you be open to sending a {p} for a review", "quick question about your creator program",
        "I'd love to feature your latest {pl} in a video"]
NOUN = {"scooter": ("e-scooter", "e-scooters"), "pc": ("gaming PC", "gaming PCs"), "drone": ("drone", "drones"),
        "headphones": ("pair of headphones", "headphones"), "sneakers": ("pair of sneakers", "sneakers")}
DEPTS = ["PR", "Press", "Brand", "Media", "Marketing", "Partnerships", "Comms", "Global PR"]

def build(key, out):
    Pn, p, brands = P[key]; W, ROW = E.W, E.ROW
    im = Image.new("RGB", (W, ROW * len(brands)), (12, 12, 13)); d = ImageDraw.Draw(im)
    for i, name in enumerate(brands):
        dept = DEPTS[i % len(DEPTS)]; y = i * ROW
        d.line([(0, y + ROW - 1), (W, y + ROW - 1)], fill=(38, 38, 40), width=2)
        cx, cy, r = 78, y + ROW // 2, 42
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=E.color(name))
        ini = "".join(q[0] for q in name.replace("-", " ").replace("&", " ").split()[:2]).upper()
        d.text((cx, cy), ini, font=E.fb(30 if len(ini) == 1 else 26), fill="white", anchor="mm")
        x = 150
        d.text((x, y + 18), "To: " + name, font=E.fb(34), fill="white")
        tw = d.textlength("To: " + name, font=E.fb(34))
        d.text((x + tw + 10, y + 27), "- " + dept, font=E.fr(24), fill=(150, 150, 155))
        d.text((W - 40, y + 22), "Sep 24", font=E.fr(26), fill=(170, 170, 175), anchor="ra")
        d.text((x, y + 60), SUBJ[i % len(SUBJ)].format(P=Pn), font=E.fb(26), fill=(235, 235, 235))
        prev = f"Hi {name} team, " + OPEN[i % len(OPEN)].format(p=NOUN[key][0], pl=NOUN[key][1])
        d.text((x, y + 93), E.fit(d, prev, E.fr(23), W - x - 110), font=E.fr(23), fill=(140, 140, 145))
        E.star(d, W - 62, y + 92, 17, (150, 150, 155))
    # search bar header like the reference ("in:sent")
    hdr = Image.new("RGB", (W, 110), (12, 12, 13)); h = ImageDraw.Draw(hdr)
    h.rounded_rectangle([24, 22, W - 24, 92], radius=35, fill=(40, 40, 43))
    h.ellipse([58, 43, 82, 67], outline="white", width=3); h.line([(79, 64), (90, 75)], fill="white", width=3)
    h.text((108, 57), "in:sent", font=E.fr(30), fill="white", anchor="lm")
    full = Image.new("RGB", (W, 110 + im.height), (12, 12, 13)); full.paste(hdr, (0, 0)); full.paste(im, (0, 110))
    full.save(out)

if __name__ == "__main__":
    for k in P: build(k, f"assets/batch2/{k}_emails.png"); print(k)
