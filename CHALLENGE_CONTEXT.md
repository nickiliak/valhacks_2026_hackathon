Hilton is unhappy with its booking system:

- They get more reserverations than they have space for
- Guests cancel their reservation, leaving empty rooms. Some even don't cancel and don't show up at all.
- If they coul;d have a system to decide when to accept a reservation, they could increase their revenue.
- They can overbook, but in case they run out of room, they will need to pay for a room in another hotel at, in average, 2.5x the rate.

Judging criteria:

Performance: net revenue calculation
Explainability: in your presentation you should explain to a non technical stakeholder how your model works and how it reaches its recommendations

Team clarifications (assumptions we agreed on):

- Deposit type does not affect profit. A cancelled booking earns 0 regardless of its deposit type; no deposit money is counted. Profit = nightly_rate x nights for guests who show up and are seated, minus walk penalties.
- The `deposit` column is NOT available to us (decided 14 Nov ~12:45). It has been dropped from `data/train.csv`. It cannot be a feature or a rule input, and feature choices are justified only by the permitted columns' own relationship to `cancelled`.
- The two hotels are completely independent. When one hotel is full, guests are NOT moved to the other hotel. Capacity, overbooking and walk penalties are handled separately per hotel, and an overflow guest is always walked to an external hotel at 2.5x their stay value.

There will also be a technical interviewer aside from the non technical stakeholders so we should be ready for technical questions just in case.