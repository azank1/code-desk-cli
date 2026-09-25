import sys, json, statistics
sys.path.insert(0, __import__("os").path.dirname(__file__))
import extend as X, adaptive_vs_fixed as M
def confirm(tasks,k=2):
    st=[];tr=[]
    for tt,base,obs in tasks:
        steps=M.CAP
        for i in range(M.CAP):
            if i+1>=k and all(obs[j]>=M.THRESHOLD for j in range(i-k+1,i+1)): steps=i+1; break
        st.append(steps); tr.append(base[steps-1]>=M.THRESHOLD)
    return dict(steps=sum(st)/len(st), true_reach=100*sum(tr)/len(tr))
def margin(tasks,m=0.05):
    st=[];tr=[]
    for tt,base,obs in tasks:
        c=next((i+1 for i in range(M.CAP) if obs[i]>=M.THRESHOLD+m),None); steps=c or M.CAP
        st.append(steps); tr.append(base[steps-1]>=M.THRESHOLD)
    return dict(steps=sum(st)/len(st), true_reach=100*sum(tr)/len(tr))
def smooth(tasks):  # stop when mean of last two obs >= threshold
    st=[];tr=[]
    for tt,base,obs in tasks:
        steps=M.CAP
        for i in range(1,M.CAP):
            if (obs[i]+obs[i-1])/2>=M.THRESHOLD: steps=i+1; break
        st.append(steps); tr.append(base[steps-1]>=M.THRESHOLD)
    return dict(steps=sum(st)/len(st), true_reach=100*sum(tr)/len(tr))
out={}
for sg in X.SIGMAS:
    rows={"confirm2":[],"margin05":[],"smooth2":[]}
    for s in X.SEEDS:
        test=X.gen(200,s,sg)[300:]
        rows["confirm2"].append(confirm(test)); rows["margin05"].append(margin(test)); rows["smooth2"].append(smooth(test))
    out[str(sg)]={k:{m:(statistics.mean(r[m] for r in v),statistics.stdev(r[m] for r in v)) for m in v[0]} for k,v in rows.items()}
    print(f"sigma={sg}: "+" | ".join(f"{k} steps {out[str(sg)][k]['steps'][0]:.2f} true {out[str(sg)][k]['true_reach'][0]:.1f}%" for k in rows),file=sys.stderr)
json.dump(out,open(__import__("os").path.join(__import__("os").path.dirname(__file__), "results2.json"),"w"),indent=1)
