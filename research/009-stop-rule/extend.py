"""009 extension: noise sweep, seed sweep, cold-start sweep over the restored benchmark.
True reach = the hidden noiseless curve is >= THRESHOLD at the stop step (not the noisy observation)."""
import sys, json, random, statistics
from math import exp
sys.path.insert(0, __import__("os").path.dirname(__file__))
import adaptive_vs_fixed as M
from cdv import AdaptivePriors, AgentLoopController

def gen(n_per_type, seed, sigma):
    rng = random.Random(seed); tasks = []
    for tt,(s0lo,s0hi,rlo,rhi) in M.TASK_TYPES.items():
        for _ in range(n_per_type):
            s0=rng.uniform(s0lo,s0hi); r=rng.uniform(rlo,rhi); base=[]; obs=[]
            for t in range(1,M.CAP+1):
                b=1.0-(1.0-s0)*exp(-r*(t-1)); base.append(b)
                obs.append(max(0.0,min(1.0,b+rng.gauss(0.0,sigma))))
            tasks.append((tt,base,obs))
    rng.shuffle(tasks); return tasks

def first_cross(xs, upto):
    for i in range(upto):
        if xs[i]>=M.THRESHOLD: return i+1
    return None

def evaluate(strategy, tasks, ctrl=None, budget=None):
    steps_l=[]; true_reach=[]; obs_reach=[]; final_true=[]
    for tt,base,obs in tasks:
        if strategy=="fixed":
            steps=budget
        elif strategy=="threshold":
            c=first_cross(obs,M.CAP); steps=c if c else M.CAP
        else:
            s=ctrl.start(goal="g",task_type=tt,model_id=M.MODEL,quality_threshold=M.THRESHOLD); steps=0
            for t in range(M.CAP):
                steps+=1
                if ctrl.step(s.session_id,obs[t])["decision"]=="stop": break
            ctrl.end(s.session_id,converged=first_cross(obs,steps) is not None)
        steps_l.append(steps); final_true.append(base[steps-1])
        true_reach.append(base[steps-1]>=M.THRESHOLD); obs_reach.append(first_cross(obs,steps) is not None)
    n=len(tasks)
    return dict(steps=sum(steps_l)/n, true_reach=100*sum(true_reach)/n, obs_reach=100*sum(obs_reach)/n, final_true=sum(final_true)/n)

def warm(priors, train):
    for tt,base,obs in train:
        c=first_cross(obs,M.CAP); stop=c if c else M.CAP
        priors.observe(M.CallObservation(task_type=tt,model_id=M.MODEL,scores=obs[:stop],latencies_ms=[1000.0]*stop,converged=c is not None,total_iterations=stop,max_iterations=M.CAP,quality_threshold=M.THRESHOLD))

def run(seed, sigma, n_train=300):
    tasks=gen(200,seed,sigma); train,test=tasks[:300],tasks[300:]
    p=AdaptivePriors(); warm(p,train[:n_train]); ctrl=AgentLoopController(p)
    return {"fixed2":evaluate("fixed",test,budget=2),"fixed6":evaluate("fixed",test,budget=6),
            "threshold":evaluate("threshold",test),"adaptive":evaluate("adaptive",test,ctrl=ctrl)}

out={"noise":{}, "coldstart":{}}
SEEDS=list(range(1,11)); SIGMAS=[0.02,0.05,0.10,0.15,0.20]
for sg in SIGMAS:
    runs=[run(s,sg) for s in SEEDS]
    out["noise"][str(sg)]={k:{m:(statistics.mean(r[k][m] for r in runs),statistics.stdev(r[k][m] for r in runs)) for m in runs[0][k]} for k in runs[0]}
    a=out["noise"][str(sg)]; print(f"sigma={sg}: threshold steps {a['threshold']['steps'][0]:.2f} true {a['threshold']['true_reach'][0]:.1f}% | adaptive steps {a['adaptive']['steps'][0]:.2f} true {a['adaptive']['true_reach'][0]:.1f}% | fixed6 true {a['fixed6']['true_reach'][0]:.1f}%",flush=True)
for nt in [0,10,30,100,300]:
    runs=[run(s,0.10,n_train=nt) for s in SEEDS]
    out["coldstart"][str(nt)]={m:(statistics.mean(r["adaptive"][m] for r in runs),statistics.stdev(r["adaptive"][m] for r in runs)) for m in runs[0]["adaptive"]}
    a=out["coldstart"][str(nt)]; print(f"train={nt}: adaptive steps {a['steps'][0]:.2f} true {a['true_reach'][0]:.1f}%",flush=True)
json.dump(out,open(__import__("os").path.join(__import__("os").path.dirname(__file__), "results.json"),"w"),indent=1)
