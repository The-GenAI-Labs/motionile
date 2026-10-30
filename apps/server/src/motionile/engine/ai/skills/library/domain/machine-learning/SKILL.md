---
name: machine-learning
description: Explaining how machine learning models learn - supervised, unsupervised and reinforcement learning, loss functions, gradient descent and learning rate, backpropagation, neural network layers, overfitting and regularization, train-validation-test splits, evaluation metrics (precision, recall, F1), decision trees, embeddings and the transformer attention mechanism. Use for training, the maths and the internals of models, not for building applications on top of an LLM (applied-ai).
metadata:
  layer: domain
---

# Machine learning

## When to use

Topics about how a model is fitted to data and why it generalizes or fails. Audience ranges from beginners who know no maths to students who can read an equation. Decide the level from the storyboard `audienceLevel` and keep one level per video. Pair with `math-equation` for formulas; never show an equation the narration does not explain in words.

## Structure

1. The task in plain terms: inputs, the output we want, and what "wrong" means.
2. A model as a function with adjustable numbers (parameters).
3. A loss that scores how wrong it is on examples.
4. A learning procedure that nudges parameters to lower the loss (gradient descent).
5. A tiny worked case with two or three numbers before any large network.
6. How we check it works on data it has not seen, and what failure looks like.

One idea per beat; do not mix training and inference in the same scene without labeling which one is on screen.

## Analogies and where they break

- Gradient descent as a hiker in fog stepping downhill. Breaks: real loss surfaces have millions of dimensions, steps use noisy mini-batches, and saddle points matter more than neat local valleys.
- Overfitting as memorizing the exam answers instead of learning the subject. Breaks: the model has no intent; it simply fits noise when it has too much capacity for the data.
- Learning rate as stride length. Breaks: the right size changes during training, so schedules exist.
- Neuron as a voting unit that weighs its inputs. Breaks: it is a weighted sum followed by a nonlinearity, nothing like a biological neuron in detail.
- Attention as a spotlight or a lookup. Breaks: it is a learned weighted average over all positions, computed with queries, keys and values.
- Embedding as coordinates of meaning. Breaks: the axes have no individual human meaning.

## Misconceptions to preempt

- "The model memorizes the training set." It can, if overfit; the goal is generalization.
- "Accuracy is enough." With rare positives a model that always says no can be 99 percent accurate and useless; use precision, recall and the confusion matrix.
- "More data or a bigger model always fixes it." Poor labels, leakage and distribution shift are not cured by scale.
- "Backpropagation is a different learning algorithm." It is an efficient application of the chain rule to compute gradients; gradient descent then uses them.
- "Neural networks are black boxes with no explanation." Hard to interpret, yes; some methods still give partial explanations. Do not overstate either way.
- "Correlation found by a model is causation."
- "Test data can be used to tune." Tuning on the test set makes the final score optimistic.

## Terminology

Say feature, label, parameter (learned) versus hyperparameter (chosen), loss (per model, to minimize), gradient, epoch, batch, mini-batch, weight, bias, activation function, layer, forward pass, backward pass, training versus inference, validation set, test set, regularization, dropout, bias-variance trade-off, data leakage, class imbalance. Use "precision" (of predicted positives, how many are right) and "recall" (of true positives, how many were found). Say "fitting" or "training", not "teaching". Avoid "the AI decided".

## Visual pairings

- math-equation: loss, update rule, softmax, attention formula, each term revealed with its meaning.
- data-chart-story: loss curves for train versus validation, decision boundary, metrics trade-off.
- flow-diagram: the training loop, forward and backward pass, data splits.
- architecture-build-up: a network from input to output layer, a transformer block.
- concept-metaphor: loss landscape, overfitting.
- data-structure-operations: a decision tree splitting data.
- comparison-split: underfit, good fit and overfit curves; supervised versus unsupervised.

## Accuracy checks

- The gradient descent update moves parameters opposite the gradient, scaled by the learning rate.
- Softmax outputs are non-negative and sum to 1.
- Scaled dot-product attention: softmax of (queries times keys transposed, divided by the square root of the key dimension), applied to values. Keep the scaling factor if the formula is shown.
- Train loss falling while validation loss rises signals overfitting.
- Precision, recall and F1 depend on a chosen threshold; F1 is the harmonic mean of precision and recall.
- Parameter counts and training costs of named models change over time; do not assert them.
- Keep notation consistent within one video (for example the same symbol for loss throughout).

## Do

- Run one tiny numeric example (a line fitted to four points) before the general idea.
- Label axes, and say whether a curve shows training or validation.
- Say which assumptions a method needs, such as independent examples.

## Don't

- Don't claim a model "understands" or "reasons" as settled fact.
- Don't show exact accuracy figures for a real dataset without naming the source and date.
- Don't present deep learning as the right tool for all problems.
