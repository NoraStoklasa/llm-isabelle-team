from .heuristics import rank_candidates
from .premises import PremisesIndex


def rank_tactics(proof_goal, suggested_tactics, selected_premises=None):
    """
    Reorder suggested Isabelle tactics so the most promising ones are tried first.
    This wraps the existing rank_candidates() function.
    """
    return rank_candidates(
        cands=suggested_tactics,
        goal=proof_goal,
        state_hint="",
        facts=selected_premises or [],
        reranker=None,
        depth=0
    )


def select_premises(proof_goal, available_premises, max_premises=5):
    """
    Select the most relevant premises/facts for the current proof goal.
    This wraps the existing PremisesIndex class.
    """
    index = PremisesIndex()

    for i, premise in enumerate(available_premises):
        index.add(f"premise_{i}", premise)

    index.finalize()

    picks = index.select(
        proof_goal,
        k_select=max_premises,
        k_rerank=max_premises
    )

    selected_ids = [fact_id for fact_id, _select_score, _rerank_score in picks]

    return index.texts_for(selected_ids)

def clean_tactic(tactic):
    """
    Clean common LLM-generated Isabelle tactic wording mistakes before ranking/testing.

    This is intentionally conservative: it only fixes obvious surface-level
    syntax issues and does not try to invent new proof strategies.
    """

    cleaned = tactic.strip()

    replacements = {
        "apply (induction ": "apply (induct ",
        "apply(induction ": "apply(induct ",

        "apply (case ": "apply (cases ",
        "apply(case ": "apply(cases ",

        "apply (simplify)": "apply simp",
        "apply(simplify)": "apply simp",

        "apply (automatic)": "apply auto",
        "apply(automatic)": "apply auto",

        "apply (blast_tac)": "apply blast",
        "apply(blast_tac)": "apply blast",
    }

    for wrong, right in replacements.items():
        cleaned = cleaned.replace(wrong, right)

    return cleaned