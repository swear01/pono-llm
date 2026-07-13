(set-logic QF_BV)
; benchmark generated from python API
(set-info :status unknown)
(declare-fun input18 () (_ BitVec 64))
(declare-fun input17 () (_ BitVec 64))
(declare-fun input15 () (_ BitVec 64))
(declare-fun input14 () (_ BitVec 64))
(declare-fun state31 () (_ BitVec 64))
(declare-fun state30 () (_ BitVec 64))
(declare-fun state28 () (_ BitVec 64))
(declare-fun state27 () (_ BitVec 64))
(assert
 (and (= state27 (bvadd (bvmul state28 state30) state31)) true true (not (= input14 (bvadd (bvmul input15 input17) input18)))))
(check-sat)
