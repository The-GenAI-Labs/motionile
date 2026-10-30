---
name: applied-ai
description: Explaining how to build with and reason about large language models as a user or application developer - tokens, context windows, prompting, system prompts, temperature, embeddings and vector search, retrieval-augmented generation (RAG), tool calling, agents and agent loops, evals, hallucination, fine-tuning versus retrieval, and prompt injection from the defender's side. Use for using LLMs in products, not for how a model is trained or the maths inside it (machine-learning).
metadata:
  layer: domain
---

# Applied AI and LLM applications

## When to use

Topics about what an LLM does at run time and how applications are built around it: prompts, retrieval, tools, agents, evaluation, cost and latency. Audience: developers, product people and curious beginners. This field moves quickly. Never state model names, prices, context sizes or benchmark rankings as facts; speak about the mechanism, and if a figure matters, tell the viewer to check the current documentation and give the date.

## Structure

1. Show what the model actually receives: a sequence of tokens (system text, history, user text), and what it returns: the next token, repeatedly.
2. State the limitation that motivates the technique (no access to private or recent data, fixed context, no ability to act).
3. Show the technique as a pipeline around the model, with the model as one box.
4. Run one concrete example end to end (a question about a company policy document, a weather lookup).
5. Show the failure mode and how it is measured or reduced.

## Analogies and where they break

- LLM as an autocomplete trained on vast text. Breaks: it is far more capable than phone autocomplete, but it still produces likely text, not verified facts.
- Context window as a desk of fixed size: the model sees only what is on it. Breaks: a crowded desk does not guarantee equal attention to everything on it.
- RAG as an open-book exam. Breaks: the student can still misread the book, and a bad search returns the wrong page.
- Embeddings as map coordinates where similar meanings sit close together. Breaks: the space has hundreds or thousands of dimensions, and closeness depends on the embedding model.
- Tool calling as the model filling in a request form that the application then processes. Breaks: the model never executes anything; the application decides whether to run it.
- Agent as an intern with a checklist and a phone. Breaks: errors compound over steps, so permissions and limits matter.

## Misconceptions to preempt

- "The model looks facts up." Without retrieval or a tool, it generates from learned patterns.
- "RAG removes hallucination." It reduces it when retrieval works; answers can still contradict or ignore the sources.
- "A longer context window means perfect recall."
- "Temperature zero is truthful." It only makes selection more deterministic, and not always bit-for-bit identical.
- "Fine-tuning teaches the model new facts reliably." It mostly shapes style, format and behavior; fresh or private knowledge usually belongs in retrieval.
- "Tokens are words." A token is a piece of text; English averages somewhat under one word per token, and other languages often take more tokens per word. Say "roughly".
- "The model remembers earlier chats." Memory exists only if the application sends it back in.

## Terminology

Say token, context window, prompt, system prompt, completion, temperature, top-p, embedding, vector database or vector index, chunking, retrieval, reranking, grounding, citation, tool call, function calling, agent loop, structured output, guardrail, eval, latency, cost per token, prompt injection. Say "hallucination" as the established term, defined as fluent output not supported by facts or sources. Avoid "the AI thinks", "knows" or "understands" as literal claims, and avoid "AGI" talk.

## Visual pairings

- flow-diagram: the RAG pipeline, an agent loop, tool call round trip.
- architecture-build-up: an LLM app growing from prompt to retrieval, tools, evals, guardrails.
- concept-metaphor: embedding space, context window.
- comparison-split: prompting versus RAG versus fine-tuning, with and without retrieval.
- timeline-sequence: a conversation turn by turn, what is sent each time.
- data-chart-story: eval pass rate across prompt versions, cost versus quality.
- kinetic-typography: one prompt and the tokens it splits into.

## Accuracy checks

- Cosine similarity ranges from -1 to 1; higher means closer in direction.
- Input and output tokens usually have different prices and both count toward the context limit.
- Chunk size and overlap are tunable trade-offs, not fixed rules.
- Prompt injection: text from documents or users can carry instructions the model may follow; defenses are separating instructions from data, least-privilege tools, output checks and human approval for risky actions. No prompt alone is a guarantee.
- Evals need a fixed test set and a metric; "it looked good" is not an eval.
- Label any example output as illustrative.

## Do

- Show the actual prompt text and the retrieved passages when explaining RAG.
- Make cost, latency and failure visible in the example.
- Distinguish what the model does from what the surrounding code does.

## Don't

- Don't rank vendors or models, or predict capabilities.
- Don't promise accuracy percentages for any technique.
- Don't show a working injection that attacks a real product.
