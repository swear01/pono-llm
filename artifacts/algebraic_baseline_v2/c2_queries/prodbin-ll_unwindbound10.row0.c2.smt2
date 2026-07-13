(set-logic QF_BV)
; benchmark generated from python API
(set-info :status unknown)
(declare-fun input15 () (_ BitVec 64))
(declare-fun input14 () (_ BitVec 64))
(declare-fun input12 () (_ BitVec 64))
(declare-fun state24 () (_ BitVec 64))
(declare-fun state23 () (_ BitVec 64))
(declare-fun state21 () (_ BitVec 64))
(assert
 (let (($x356 (not (= input12 (bvmul input14 input15)))))
(let (($x228 (= state21 (bvmul state23 state24))))
(and $x228 true true $x356))))
(check-sat)
