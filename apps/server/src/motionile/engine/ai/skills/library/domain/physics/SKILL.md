---
name: physics
description: Explains school and early-undergraduate physics for video - mechanics (motion, forces, Newton's laws, energy, momentum, gravity, orbits), waves, sound and light, optics, thermodynamics and heat, electricity and circuits, magnetism, relativity and quantum ideas at a conceptual level. Use for phenomena, laws, SI units, free fall, why the sky is blue, how a circuit works, what energy is, speed of light, black holes explained simply, misconceptions about forces and motion.
metadata:
  layer: domain
---

# Physics

## When to use

Queries about a physical phenomenon, law, quantity or everyday effect, from school mechanics to introductory modern physics. Chemistry-of-reactions topics belong to `chemistry`; this skill covers matter only through forces, energy and fields.

## Structure

1. Hook with an observation the viewer has seen (a falling object, a dimming light, a rainbow).
2. Name the quantity or law and its plain-language meaning before any equation.
3. Show the mechanism as a picture with arrows, labelled bodies and a clear system boundary.
4. Give the relation (equation), define each symbol with its SI unit, then compute one example with numbers and units.
5. Contrast with the common wrong prediction and show what an experiment or the Moon actually shows.
6. State the limit of the model (when it stops being true).

Beginner: observation, one law in words, one example. Intermediate: the equation and a worked number. Advanced: derivation sketch, approximations, regime of validity.

## Analogies and where they break

- Water in pipes for circuits: voltage as pressure, current as flow rate; breaks because electrons are not consumed and the fluid is not "used up" along the way.
- Ripples on a pond for waves: shows propagation without bulk transport; breaks for light, which needs no medium, and for quantum particles.
- Rubber sheet for gravity: shows curved paths; breaks because the sheet needs an external "down" and a real spacetime is four-dimensional.
- Solar system for the atom: breaks because electrons occupy probability clouds (orbitals), not paths.
- Ball on a hill for potential energy: good for energy conversion; breaks for non-gravitational potentials.
- Traffic jam for heat flow or pressure: breaks on conservation details; use only for qualitative ideas.

## Misconceptions to preempt

- Heavier objects do not fall faster in a vacuum; air resistance causes the difference (the Apollo 15 hammer and feather on the Moon).
- A moving object needs no continuing force to keep moving; forces change velocity (Newton's first law).
- Mass and weight differ: mass in kilograms, weight is a force in newtons, W = mg.
- There is no "centrifugal force" pushing an orbit outward in an inertial frame; the inward net force changes direction.
- Action-reaction pairs act on different bodies, so they never cancel each other.
- Astronauts float because they are in free fall, not because gravity is absent; at the ISS altitude gravity is about nine tenths of its surface value.
- Current is not used up in a circuit; energy is transferred, current is the same around a series loop.
- Heat and temperature differ; heat is energy transferred, temperature measures average kinetic energy per particle.
- Seasons come from the 23.4 degree tilt of Earth's axis, not from distance to the Sun.
- Energy is transferred and converted, not created or destroyed; E = mc^2 says a system's energy and rest mass are linked, not that everyday objects are about to turn into energy.
- Speed and velocity differ; a car circling at constant speed is accelerating.

## Terminology and notation

- SI base units: metre, kilogram, second, ampere, kelvin, mole, candela. Derived: newton = kg m/s^2, joule = N m, watt = J/s, pascal = N/m^2, hertz = 1/s, volt = J/C, ohm = V/A.
- Quantity symbols in italic (m, v, F); unit symbols upright with a space after the number: 9.81 m/s^2, 5 kg, 300 K. Kelvin has no degree sign; Celsius does.
- Report answers with units and sensible significant figures; do not output more digits than the inputs justify.
- Vectors have direction: say "velocity" not "speed" when direction matters. Use "net force", "work done", "kinetic energy", "momentum" (p = mv).
- Name the system and the sign convention before using a sign.

## Anchors worth stating

- g is about 9.81 m/s^2 at Earth's surface (9.8 for school use).
- The speed of light in vacuum is exactly 299,792,458 m/s; light from the Sun takes about 8.3 minutes to reach Earth (1 astronomical unit is about 149.6 million km).
- Sound in air at 20 degrees C is about 343 m/s.
- 0 degrees C is 273.15 K; 1 kWh is 3.6 million joules.
- Earth's radius is about 6,371 km; a hydrogen atom is about 10^-10 m across; a nucleus about 10^-15 m.
- The Planck constant is exactly 6.62607015 x 10^-34 J s.

## Pair with visual skills

- `concept-metaphor`: intuition scenes (field lines, free fall, the pipe analogy).
- `math-equation`: deriving v = u + at, F = ma, energy balance, Ohm's law.
- `data-chart-story`: graphs of position, velocity, acceleration; measured data; scales of size.
- `flow-diagram`: energy transfers, circuit current paths, chain of cause and effect.
- `comparison-split`: series versus parallel, mass versus weight, with and without air.
- `timeline-sequence`: history of a discovery or stages of a process (stellar life).
- `kinetic-typography`: the law in one line.

## Accuracy checks for the planner

- Check dimensions and units on every equation shown; a worked example must carry units through each step.
- Check the sign and direction of every arrow; free-body diagrams show forces on one body only.
- Check that numbers use the same unit system (convert km/h to m/s by dividing by 3.6).
- Keep classical results out of regimes where they fail (near light speed, atomic scales) and say so.
- Use "theory" in the scientific sense: a well-tested explanatory framework.

## Don't

- Say a "force of inertia", "relativistic mass" or that electrons "flow at the speed of light"; the signal travels fast, the electrons drift slowly, of order a millimetre per second or less.
- Claim quantum mechanics shows consciousness changes reality, or that a measurement needs a human observer.
- Present an analogy as the mechanism without naming where it fails.
- Show an equation without defining every symbol and unit.
- Give medical, safety-critical or mains-electricity instructions.
