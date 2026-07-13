(set-logic QF_BV)
; benchmark generated from python API
(set-info :status unknown)
(declare-fun input15 () (_ BitVec 32))
(declare-fun input11 () (_ BitVec 32))
(declare-fun input13 () (_ BitVec 32))
(declare-fun state25 () (_ BitVec 32))
(declare-fun state21 () (_ BitVec 32))
(declare-fun state23 () (_ BitVec 32))
(assert
 (let (($x372 (not (= input13 (bvmul input11 input15)))))
(and (= state23 (bvmul state21 state25)) true true $x372)))
(check-sat)
