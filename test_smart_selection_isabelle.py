from prover.smart_selection import rank_tactics, select_premises
from prover.isabelle_api import (
    start_isabelle_server,
    get_isabelle_client,
    run_theory,
    finished_ok,
    graceful_terminate,
)


def extract_session_id(session_start_result):
    """
    The Isabelle client may return either a plain session id string
    or a list of response objects. This extracts the actual session id.
    """
    if isinstance(session_start_result, str):
        return session_start_result

    for response in session_start_result or []:
        body = getattr(response, "response_body", None)

        sid = getattr(body, "session_id", None)
        if sid:
            return sid

        if isinstance(body, dict) and body.get("session_id"):
            return body["session_id"]

    raise RuntimeError(f"Could not extract session_id from: {session_start_result}")


def check_finisher(isabelle, session_id, goal, tactic):
    """
    Test a tactic that should finish the proof, such as:
        by simp
        by auto
    """
    theory = f"""theory Scratch
imports Main
begin

lemma "{goal}"
  {tactic}

end
"""

    resps = run_theory(isabelle, session_id, theory, timeout_s=60)
    ok, info = finished_ok(resps)
    return ok


def check_apply_step(isabelle, session_id, goal, tactic):
    """
    Test an apply-style tactic as a single accepted Isabelle step.

    It does not need to finish the proof. We use oops afterwards so Isabelle
    can close the unfinished proof attempt.
    """
    theory = f"""theory Scratch
imports Main
begin

lemma "{goal}"
  {tactic}
  print_state
  oops

end
"""

    resps = run_theory(isabelle, session_id, theory, timeout_s=60)
    ok, info = finished_ok(resps)
    return ok


def main():
    proof_goal = "map f (xs @ ys) = map f xs @ map f ys"

    suggested_tactics = [
        "apply blast",
        "apply simp",
        "apply auto",
        "apply (induction xs)",
    ]

    available_premises = [
        "map_append: map f (xs @ ys) = map f xs @ map f ys",
        "rev_rev_ident: rev (rev xs) = xs",
        "append_assoc: (xs @ ys) @ zs = xs @ (ys @ zs)",
        "length_map: length (map f xs) = length xs",
    ]

    print("=== Smart selection output ===")

    selected_premises = select_premises(
        proof_goal,
        available_premises,
        max_premises=5,
    )

    ranked_tactics = rank_tactics(
        proof_goal,
        suggested_tactics,
        selected_premises,
    )

    print("\nSelected premises:")
    for premise in selected_premises:
        print("-", premise)

    print("\nRanked tactics:")
    for tactic in ranked_tactics:
        print("-", tactic)


    print("\n=== Isabelle checks ===")

    server_info, proc = start_isabelle_server(
        name="smart_selection_test",
        log_file="smart_selection_server.log",
    )

    print("Server:", server_info)

    isabelle = get_isabelle_client(server_info)

    try:
        session_start_result = isabelle.session_start(session="HOL")
        session_id = extract_session_id(session_start_result)
        print("Session ID:", session_id)

        print("\nFinisher checks:")
        for finisher in ["by simp", "by auto"]:
            ok = check_finisher(isabelle, session_id, proof_goal, finisher)
            print(f"{finisher}: {'PASS' if ok else 'FAIL'}")

        print("\nApply-step checks:")
        for tactic in ranked_tactics:
            if tactic.strip().startswith("apply"):
                ok = check_apply_step(isabelle, session_id, proof_goal, tactic)
                print(f"{tactic}: {'PASS' if ok else 'FAIL'}")

    finally:
        try:
            isabelle.shutdown()
        except Exception:
            pass

        graceful_terminate(proc)


if __name__ == "__main__":
    main()