(set-logic QF_BV)
; benchmark generated from python API
(set-info :status unknown)
(declare-fun input14 () (_ BitVec 64))
(declare-fun input13 () (_ BitVec 64))
(declare-fun input12 () (_ BitVec 64))
(declare-fun state24 () (_ BitVec 64))
(declare-fun state23 () (_ BitVec 64))
(declare-fun state22 () (_ BitVec 64))
(assert
 (let (($x120 (= state22 (bvmul state23 state24))))
(and $x120 true true (not (= input12 (bvmul input13 input14))))))
(check-sat)
