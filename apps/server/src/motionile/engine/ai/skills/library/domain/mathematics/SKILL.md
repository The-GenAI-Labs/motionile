---
name: mathematics
description: Explains school and early-undergraduate mathematics for video - arithmetic, fractions, algebra, functions and graphs, geometry, trigonometry, calculus (limits, derivatives, integrals), probability, descriptive statistics, linear algebra basics, number theory, sequences and series, proofs. Use for theorems, formulas, equations, notation, why a rule works, paradoxes and puzzles (Monty Hall, birthday problem, 0.999 equals 1, Pythagoras, Euler's number), not for machine-learning maths or algorithm complexity.
metadata:
  layer: domain
---

# Mathematics

## When to use

Queries about a mathematical idea, rule, theorem, formula, proof or puzzle at school or first-year university level. For the animation of equations themselves, pair with `math-equation`.

## Structure

1. Hook with a concrete question or a surprising result the viewer can check in their head.
2. Intuition first: a picture, a count or a physical situation before any symbol.
3. Introduce notation one symbol at a time, each tied to what it stood for in the picture.
4. Work one small numeric case, then state the general rule.
5. Show why it works (a visual proof, a pattern or a short argument), not only that it works.
6. Name the misconception the viewer is most likely holding and break it with a counter-example.
7. End with the rule restated in one line and one place it is used.

Beginner: no symbols beyond arithmetic and one variable. Intermediate: functions, graphs, the general rule. Advanced: state assumptions, proof idea, edge cases.

## Analogies and where they break

- Fraction as pieces of a pizza: breaks for improper fractions and for division by a fraction; use a number line instead.
- Function as a machine: one input gives exactly one output; breaks for relations such as a circle, which fails the vertical-line test.
- Derivative as speedometer reading: instantaneous rate at one moment; breaks if described as "tiny change divided by tiny change" without the limit.
- Integral as accumulated area: negative where the curve lies below the axis; area and integral differ then.
- Probability as long-run frequency: says nothing certain about the next trial.
- Vectors as arrows: fine in the plane; breaks for function spaces, so do not claim a vector is only an arrow.

## Misconceptions to preempt

- (a + b)^2 is a^2 + 2ab + b^2, not a^2 + b^2; show the square with four regions.
- The square root of x^2 is |x|, not x; the square root symbol means the non-negative root.
- Multiplication does not always enlarge and division does not always shrink (numbers below 1, negatives).
- Division by zero is undefined; infinity is not a real number, so never write "infinity is a very large number".
- 0.999... equals 1 exactly; it is a limit statement about an infinite decimal, not "almost 1".
- A derivative of zero marks a stationary point, not necessarily a maximum or minimum (x^3 at 0).
- Examples do not prove a general statement; one counter-example disproves it.
- Independent events have no memory: after five heads a fair coin is still 1/2 (gambler's fallacy).
- Monty Hall: switching wins with probability 2/3 when the host knowingly opens a losing door.
- The equals sign states that both sides have the same value, not "the answer comes next".

## Terminology and notation

- Variables and functions in italic: f(x), x, n. Constants and operators upright: e, i, sin, ln, d.
- Use "factor" for multiplication parts and "term" for addition parts; "solve" an equation, "simplify" an expression.
- Sets: {1, 2, 3}, membership x in A, subsets, union, intersection. Intervals: [a, b] closed, (a, b) open.
- Angles: degrees or radians, always say which; 180 degrees equals pi radians. Calculus formulas for sin and cos assume radians.
- Probability is a number from 0 to 1 (percent only for audiences who expect it). Mean, median and mode are different "averages"; name which one.
- Write the multiplication dot or times sign, not the letter x; write minus as a true minus, not a hyphen.
- Use Latin letters, digits, sub- and superscripts. Greek letters, arrows and operators can fall back to a system font in the renderer: spell the name once ("theta") or draw the glyph with SVG.

## Anchors worth stating (all exact or standard)

- Pythagoras: a^2 + b^2 = c^2 for right triangles only; 3-4-5 is the smallest integer triple.
- Sum of 1 to n is n(n + 1)/2, so 1 to 100 is 5,050.
- 2^10 is 1,024; 10^6 seconds is about 11.6 days; 10^9 seconds is about 31.7 years.
- Angles of a triangle in the plane sum to 180 degrees; of a quadrilateral, 360.
- pi is about 3.14159 and irrational; e is about 2.71828; the golden ratio is about 1.618.
- Birthday problem: 23 people give a probability just over 50 percent of a shared birthday.
- There are infinitely many primes (Euclid); 2 is the only even prime; 1 is not prime.

## Pair with visual skills

- `math-equation`: derivations, step-by-step algebra, identities, formulas appearing term by term.
- `data-chart-story`: functions, distributions, probability outcomes, growth curves.
- `concept-metaphor`: intuition scenes (function machine, area under a curve).
- `comparison-split`: two methods, linear versus exponential, mean versus median.
- `timeline-sequence`: history of a result or the order of proof steps.
- `kinetic-typography`: the hook question and the one-line rule.

## Accuracy checks for the planner

- Every worked numeric example must be recomputed; show intermediate values.
- State domain restrictions (denominators not zero, logarithm arguments positive, square roots of non-negatives).
- Keep units and angle mode consistent; keep one letter for one meaning in a video.
- A "proof" scene must say which statement is assumed and which is shown.
- Name the theorem correctly and credit it only when certain of the attribution.

## Don't

- Claim a result holds "always" without its conditions (Pythagoras needs a right angle; the product rule of probability needs independence).
- Present an intuition as a proof or call a pattern from three cases a rule.
- Introduce more than one new symbol per beat or leave a symbol undefined on screen.
- Use "obviously", "simply" or "just"; they hide the step the viewer is missing.
- State a historical date or attribution you are not sure of.
