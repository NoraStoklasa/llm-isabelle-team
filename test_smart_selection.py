from prover.smart_selection import rank_tactics, select_premises, clean_tactic

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

selected_premises = select_premises(
    proof_goal,
    available_premises,
    max_premises=5
)

ranked_tactics = rank_tactics(
    proof_goal,
    suggested_tactics,
    selected_premises
)

print("Clean tactic test:")
print(clean_tactic("apply (induction xs)"))

print("\nSelected premises:")
for premise in selected_premises:
    print("-", premise)

print("\nRanked tactics:")
for tactic in ranked_tactics:
    print("-", tactic)