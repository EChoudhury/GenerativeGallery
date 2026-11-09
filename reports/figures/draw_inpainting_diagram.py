"""Create a slide-ready inpainting explainer as PNG and editable SVG."""
from pathlib import Path
import math
from html import escape
from PIL import Image, ImageDraw, ImageFont

OUT=Path(__file__).resolve().parent
W,H,S=1920,1080,2
BG='#F8F7F2';INK='#26372E';MUTED='#747C72';LINE='#D8DDD1';GREEN='#365C47';PALE='#E8EDE3';MASK='#F0EDCD';GOLD='#A79C56';FAINT='#AAB3A3'
img=Image.new('RGB',(W*S,H*S),BG);d=ImageDraw.Draw(img)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', f'<rect width="{W}" height="{H}" fill="{BG}"/>']
regular='/System/Library/Fonts/Supplemental/Arial.ttf';bold='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def rect(x,y,w,h,fill,stroke=None,r=0,width=2):
 box=[round(v*S) for v in [x,y,x+w,y+h]]
 d.rounded_rectangle(box,radius=r*S,fill=fill,outline=stroke,width=width*S)
 svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="{width}"/>')
def line(points,fill,width=2,dash=False):
 if dash:
  for a,b in zip(points[:-1],points[1:]):
   distance=math.dist(a,b);n=max(1,round(distance/10))
   for i in range(0,n,2):
    start=(a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n);end=(a[0]+(b[0]-a[0])*min(i+1,n)/n,a[1]+(b[1]-a[1])*min(i+1,n)/n)
    d.line([(round(x*S),round(y*S)) for x,y in [start,end]],fill=fill,width=width*S)
 else:d.line([(round(x*S),round(y*S)) for x,y in points],fill=fill,width=width*S)
 svg.append('<polyline points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in points)+f'" fill="none" stroke="{fill}" stroke-width="{width}" stroke-linecap="round"'+(' stroke-dasharray="8 7"' if dash else '')+'/>')
def text(x,y,value,size=28,color=INK,weight=False,anchor='left'):
 font=ImageFont.truetype(bold if weight else regular,size*S)
 d.text((x*S,y*S),value,font=font,fill=color,anchor={'left':'lt','center':'mt','right':'rt'}[anchor])
 svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial,Helvetica,sans-serif" font-size="{size}" font-weight="{700 if weight else 400}" dominant-baseline="text-before-edge" text-anchor="'+{'left':'start','center':'middle','right':'end'}[anchor]+f'">{escape(value)}</text>')
def arrow(x,y1,y2,color=GREEN):
 line([(x,y1),(x,y2-12)],color,3)
 pts=[(x-7,y2-12),(x+7,y2-12),(x,y2)]
 d.polygon([(a*S,b*S) for a,b in pts],fill=color)
 svg.append(f'<polygon points="{x-7},{y2-12} {x+7},{y2-12} {x},{y2}" fill="{color}"/>')
def waveform(x,y,w,h,color,seed=1):
 for i in range(1,int(w/7)):
  t=i*7/w
  envelope=.18+.52*abs(math.sin(t*14+seed))+.3*abs(math.sin(t*29+seed*1.7))
  amp=h*.42*envelope
  line([(x+i*7,y-amp),(x+i*7,y+amp)],color,3)

def step(y,n,a,b):
 rect(90,y,48,48,PALE,r=24)
 text(114,y+10,n,22,GREEN,True,'center')
 text(90,y+65,a,26,INK,True)
 text(90,y+99,b,25,MUTED)

text(100,50,'HOW IT WORKS',18,MUTED,True)
text(100,93,'Generate the music between two artworks.',52,INK,True)
text(100,165,'Use both ends as context. Inpaint the missing middle. Keep only the newly generated audio.',27,MUTED)

X,A,C,B=390,390,600,390
cx=X+A;bx=cx+C;center=cx+C/2
step(262,'01','Input','reference')
text(X+A/2,228,'Artwork A',29,INK,True,'center')
text(center,228,'Missing middle',29,INK,True,'center')
text(bx+B/2,228,'Artwork B',29,INK,True,'center')
rect(X,278,A,128,PALE,LINE,7);rect(cx+5,278,C-10,128,MASK,'#D2CCA2',7);rect(bx,278,B,128,PALE,LINE,7)
waveform(X+20,342,A-40,88,'#7F957D',2);waveform(bx+20,342,B-40,65,'#8C96A2',5)
line([(cx+32,342),(bx-32,342)],GOLD,2,True)
text(center,311,'MASKED INTERVAL',19,GOLD,True,'center')
text(X+A/2,421,'Last 8 seconds · existing audio',22,MUTED,False,'center')
text(center,421,'12 seconds · to be generated',22,MUTED,False,'center')
text(bx+B/2,421,'First 8 seconds · existing audio',22,MUTED,False,'center')
arrow(center,457,480)
rect(center-190,483,380,49,GREEN,r=25)
text(center,494,'STABILITY AI · INPAINT',20,'#FFFFFF',True,'center')
arrow(center,536,562)

step(581,'02','Generated','result')
rect(X,584,A,128,'#F1F2EC',LINE,7);rect(cx+5,584,C-10,128,PALE,GREEN,7,3);rect(bx,584,B,128,'#F1F2EC',LINE,7)
waveform(X+20,648,A-40,88,'#B9C1B2',2);waveform(cx+25,648,C-50,92,GREEN,3);waveform(bx+20,648,B-40,65,'#BCC1C6',5)
text(X+A/2,728,'Reference only — remove',22,MUTED,False,'center')
text(center,728,'New music informed by A + B',24,GREEN,True,'center')
text(bx+B/2,728,'Reference only — remove',22,MUTED,False,'center')
line([(cx+5,714),(cx+5,856)],'#9BAD8D',2,True);line([(bx-5,714),(bx-5,856)],'#9BAD8D',2,True)
arrow(center,770,827)
text(center,845,'KEEP ONLY THE GENERATED MIDDLE',20,GREEN,True,'center')
rect(cx+5,884,C-10,98,GREEN,r=7)
waveform(cx+30,933,C-60,65,'#DCE8C5',3)
text(center,1000,'Prepare a loop → use as the middle grid cell',25,INK,False,'center')
svg.append('</svg>')
img.save(OUT/'audio-inpainting-explained-v1.png')
(OUT/'audio-inpainting-explained-v1.svg').write_text('\n'.join(svg))
print(OUT/'audio-inpainting-explained-v1.png')
print(OUT/'audio-inpainting-explained-v1.svg')
