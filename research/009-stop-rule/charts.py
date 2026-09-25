import json
B=__import__("os").path.dirname(__file__)
R=json.load(open(f"{B}/results.json")); R2=json.load(open(f"{B}/results2.json"))
SIG=[0.02,0.05,0.10,0.15,0.20]
BG="#0d1117"; FG="#e6edf3"; GRID="#30363d"; MUTED="#8b949e"
COL={"fixed6":"#8b949e","threshold":"#f85149","adaptive":"#d2a8ff","confirm2":"#3fb950","smooth2":"#e3b341","obs":"#58a6ff"}
def head(title,sub,w=1600,h=900):
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:{BG}}}'
            f'.t{{font-family:"DejaVu Sans",sans-serif;fill:{FG}}}.m{{font-family:"DejaVu Sans Mono",monospace}}</style></head><body>'
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"><rect width="{w}" height="{h}" fill="{BG}"/>'
            f'<text x="70" y="70" class="t" font-size="30" font-weight="700">{title}</text><text x="70" y="104" class="t m" font-size="17" fill="{MUTED}">{sub}</text>')
def axes(x0,y0,x1,y1,xs,xlab,ylo,yhi,ystep,ylab,xfmt=lambda v:f"{v:g}"):
    s=""; n=len(xs)
    X=lambda i: x0+(x1-x0)*i/(n-1); Y=lambda v: y1-(y1-y0)*(v-ylo)/(yhi-ylo)
    v=ylo
    while v<=yhi+1e-9:
        s+=f'<line x1="{x0}" y1="{Y(v)}" x2="{x1}" y2="{Y(v)}" stroke="{GRID}" stroke-width="1"/><text x="{x0-14}" y="{Y(v)+6}" class="t m" font-size="15" fill="{MUTED}" text-anchor="end">{v:g}</text>'; v+=ystep
    for i,x in enumerate(xs): s+=f'<text x="{X(i)}" y="{y1+28}" class="t m" font-size="15" fill="{MUTED}" text-anchor="middle">{xfmt(x)}</text>'
    s+=f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{MUTED}" stroke-width="1.5"/>'
    s+=f'<text x="{(x0+x1)/2}" y="{y1+62}" class="t" font-size="17" fill="{MUTED}" text-anchor="middle">{xlab}</text>'
    s+=f'<text transform="translate({x0-64},{(y0+y1)/2}) rotate(-90)" class="t" font-size="17" fill="{MUTED}" text-anchor="middle">{ylab}</text>'
    return s,X,Y
def line(X,Y,vals,col,label,sds=None,dash=""):
    pts=" ".join(f"{X(i)},{Y(v)}" for i,v in enumerate(vals))
    s=f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="3.5" {"stroke-dasharray=\"9 6\"" if dash else ""}/>'
    for i,v in enumerate(vals):
        if sds: s+=f'<line x1="{X(i)}" y1="{Y(v-sds[i])}" x2="{X(i)}" y2="{Y(v+sds[i])}" stroke="{col}" stroke-width="2"/>'
        s+=f'<circle cx="{X(i)}" cy="{Y(v)}" r="5" fill="{col}"/>'
    return s
def legend(items,x=190,y=170):
    s=f'<rect x="{x-16}" y="{y-26}" width="470" height="{24*len(items)+18}" rx="8" fill="#161b22" stroke="#30363d"/>'
    for i,(col,lab,dash) in enumerate(items):
        yy=y+24*i; s+=f'<line x1="{x}" y1="{yy-5}" x2="{x+34}" y2="{yy-5}" stroke="{col}" stroke-width="3.5" {"stroke-dasharray=\"8 6\"" if dash else ""}/><text x="{x+46}" y="{yy}" class="t" font-size="16" fill="{FG}">{lab}</text>'
    return s
foot='<text x="1530" y="866" class="t m" font-size="15" fill="#6e7681" text-anchor="end">@azankhyder · 10 seeds × 300 tasks, error bars = 1 sd</text></svg></body></html>'

# Chart 1: true reach vs noise
h=head("Figure 1. A stop rule that trusts one score collapses under noise","true reach = hidden quality ≥ 0.80 at the step the loop stopped; a fixed six-step budget never reads the score, so it never gets fooled")
ax,X,Y=axes(150,150,1330,760,SIG,"judge noise σ (sd of the per-step score)",40,100,10,"tasks truly reaching the bar (%)")
h+=ax
for k,lab in (("fixed6","fixed budget = 6"),("threshold","stop at first score ≥ 0.80"),("adaptive","CDV adaptive (Bayesian + plateau + threshold)")):
    h+=line(X,Y,[R["noise"][str(s)][k]["true_reach"][0] for s in SIG],COL[k],lab,[R["noise"][str(s)][k]["true_reach"][1] for s in SIG])
h+=line(X,Y,[R2[str(s)]["confirm2"]["true_reach"][0] for s in SIG],COL["confirm2"],"confirm-2",[R2[str(s)]["confirm2"]["true_reach"][1] for s in SIG])
h+=legend([(COL["confirm2"],"confirm-2: two consecutive scores ≥ 0.80",0),(COL["fixed6"],"fixed budget = 6 (never reads the score)",0),(COL["threshold"],"threshold: stop at first score ≥ 0.80",0),(COL["adaptive"],"CDV adaptive: threshold + plateau + Bayesian guards",0)],x=190,y=640)
open(f"{B}/fig1.html","w").write(h+foot)

# Chart 2: observed vs true, threshold rule
h=head("Figure 2. What the loop believed vs what was true","the threshold rule under noise: the observed score crossed the bar in ~99.5% of runs at every noise level; the hidden quality did not")
ax,X,Y=axes(150,150,1330,760,SIG,"judge noise σ",40,100,10,"% of runs")
h+=ax
h+=line(X,Y,[R["noise"][str(s)]["threshold"]["obs_reach"][0] for s in SIG],COL["obs"],"observed: score ≥ 0.80 at stop")
h+=line(X,Y,[R["noise"][str(s)]["threshold"]["true_reach"][0] for s in SIG],COL["threshold"],"true: hidden quality ≥ 0.80 at stop",[R["noise"][str(s)]["threshold"]["true_reach"][1] for s in SIG])
# gap shading
top=[R["noise"][str(s)]["threshold"]["obs_reach"][0] for s in SIG]; bot=[R["noise"][str(s)]["threshold"]["true_reach"][0] for s in SIG]
poly=" ".join(f"{X(i)},{Y(v)}" for i,v in enumerate(top))+" "+" ".join(f"{X(i)},{Y(v)}" for i,v in reversed(list(enumerate(bot))))
h+=f'<polygon points="{poly}" fill="#f85149" fill-opacity="0.12"/><text x="{X(3)}" y="{(Y(top[3])+Y(bot[3]))/2}" class="t" font-size="18" fill="#f85149" text-anchor="middle">the loop stopped on a lucky score</text>'
h+=legend([(COL["obs"],"observed: the score the loop saw was ≥ 0.80 when it stopped",0),(COL["threshold"],"true: the hidden quality was ≥ 0.80 when it stopped",0)],x=190,y=640)
open(f"{B}/fig2.html","w").write(h+foot)

# Chart 3: cold start
NT=[0,10,30,100,300]
h=head("Figure 3. The Bayesian guard with empty priors stops too early","σ = 0.10; adaptive stopping warmed on 0 … 300 prior tasks; the threshold rule at this noise level: 3.54 steps, 71.2% true reach")
ax,X,Y=axes(150,150,1330,760,NT,"warm-up tasks seen by the priors",40,80,10,"true reach (%)",xfmt=lambda v:str(v))
h+=ax
h+=line(X,Y,[R["coldstart"][str(n)]["true_reach"][0] for n in NT],COL["adaptive"],"CDV adaptive",[R["coldstart"][str(n)]["true_reach"][1] for n in NT])
h+=f'<line x1="150" y1="{Y(71.2)}" x2="1330" y2="{Y(71.2)}" stroke="{COL["threshold"]}" stroke-width="2" stroke-dasharray="8 6"/>'
for i,n in enumerate(NT): h+=f'<text x="{X(i)}" y="{Y(R["coldstart"][str(n)]["true_reach"][0])-16}" class="t m" font-size="14" fill="{MUTED}" text-anchor="middle">{R["coldstart"][str(n)]["steps"][0]:.2f} steps</text>'
h+=legend([(COL["adaptive"],"CDV adaptive, true reach after N warm-up tasks",0),(COL["threshold"],"threshold rule at the same noise (71.2%)",1)],x=190,y=640)
open(f"{B}/fig3.html","w").write(h+foot)

# Chart 4: steps vs true reach scatter (the trade-off)
h=head("Figure 4. Steps spent vs quality actually reached (σ = 0.10)","every strategy, one point each; up and left is better")
ax,X,Y=axes(150,150,1330,760,[2,3,4,5,6],"mean steps per task",20,100,10,"true reach (%)")
h+=ax
Xv=lambda v: 150+(1330-150)*(v-2)/4
pts=[("fixed budget = 2",R["noise"]["0.1"]["fixed2"],COL["fixed6"]),("fixed budget = 6",R["noise"]["0.1"]["fixed6"],COL["fixed6"]),("threshold",R["noise"]["0.1"]["threshold"],COL["threshold"]),("CDV adaptive",R["noise"]["0.1"]["adaptive"],COL["adaptive"]),("confirm-2",R2["0.1"]["confirm2"],COL["confirm2"]),("smooth-2",R2["0.1"]["smooth2"],COL["smooth2"]),("margin +0.05",R2["0.1"]["margin05"],"#ffa657")]
for lab,m,c in pts:
    x=Xv(m["steps"][0]); y=Y(m["true_reach"][0]); dy=-16 if lab!="CDV adaptive" else 26
    h+=f'<circle cx="{x}" cy="{y}" r="9" fill="{c}"/><text x="{x}" y="{y+dy}" class="t" font-size="16" fill="{c}" text-anchor="middle">{lab}</text>'
open(f"{B}/fig4.html","w").write(h+foot)
print("ok")
