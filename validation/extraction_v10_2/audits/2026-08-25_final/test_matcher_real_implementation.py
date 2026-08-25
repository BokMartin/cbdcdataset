import sys, itertools, random
sys.path.insert(0, '/home/claude/audit/CLAUDE_AUDIT_COMPLETION_PACKAGE_v10_2/repo/x/scripts')
from evaluate_extraction_v10_1 import one_to_one_pairs

def match(nl, nr, scored):  # scored: {(l,r):score}
    edges=[(l,r,s,None) for (l,r),s in scored.items()]
    return sorted((l,r) for l,r,s,m in one_to_one_pairs(nl,nr,edges))

def one_to_one(pairs):
    ls=[l for l,_ in pairs]; rs=[r for _,r in pairs]
    assert len(ls)==len(set(ls)) and len(rs)==len(set(rs))

def test_p1_p5_augmenting_path():
    p=match(2,2,{(0,0):0.99,(0,1):0.85,(1,0):0.85})
    one_to_one(p); assert len(p)==2, p

def test_p2_cardinality_over_score():
    p=match(2,2,{(0,0):1.00,(0,1):0.85,(1,0):0.85})
    assert len(p)==2, p

def test_p3_score_among_max_cardinality():
    p=match(2,2,{(0,0):0.95,(0,1):0.81,(1,0):0.81,(1,1):0.94})
    assert set(p)=={(0,0),(1,1)}, p

def test_p4_determinism_under_ordering():
    scored={(0,0):0.9,(0,1):0.9,(1,0):0.9,(1,1):0.9}
    ref=None
    for perm in itertools.permutations(list(scored.items())):
        edges=[(l,r,s,None) for (l,r),s in perm]
        out=sorted((l,r) for l,r,s,m in one_to_one_pairs(2,2,edges))
        one_to_one(out)
        if ref is None: ref=out
        assert out==ref, (perm,out,ref)

def test_p6_duplicate_dedup():
    p=match(1,2,{(0,0):0.95,(0,1):0.95})
    one_to_one(p); assert len(p)==1
    assert 1+2-len(p)==2  # union workload

def test_regression_matches_bounded():
    scored={(l,r):0.9 for l in range(23) for r in range(141)}
    p=match(23,141,scored)
    one_to_one(p); assert len(p)<=23 and len(p)==23

def test_large_random_determinism_and_validity():
    rnd=random.Random(42)
    edges=[(l,r,round(rnd.uniform(0.80,1.0),6),None) for l in range(40) for r in range(40) if rnd.random()<0.2]
    a=sorted((l,r) for l,r,s,m in one_to_one_pairs(40,40,edges))
    b=sorted((l,r) for l,r,s,m in one_to_one_pairs(40,40,list(reversed(edges))))
    one_to_one(a); assert a==b
