(set-logic QF_BV)
; benchmark generated from python API
(set-info :status unknown)
(declare-fun input12 () (_ BitVec 32))
(declare-fun input7 () (_ BitVec 32))
(declare-fun input10 () (_ BitVec 32))
(declare-fun state23 () (_ BitVec 32))
(declare-fun state18 () (_ BitVec 32))
(declare-fun state21 () (_ BitVec 32))
(assert
 (let (($x449 (not (= input10 (bvmul input7 input12)))))
(let (($x58 (= state21 (bvmul state18 state23))))
(and $x58 true true $x449))))
(check-sat)
