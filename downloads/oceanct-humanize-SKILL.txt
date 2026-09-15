---
name: oceanct-humanize
description: Draft or revise Chinese learning notes and technical blog posts using the author's samples, familiar examples, and connected explanations while preserving facts, conditions, and citations.
---

# OceanCT's Humanize Skill

Read the user's draft, source material, and writing samples before drafting or revising. These instructions are written in English; write the article in Chinese unless the user requests another language.

## Narrative Technical Notes

Write as an author explaining a problem they are learning to understand. Follow the question through the relevant concepts and boundaries. When the user provides a writing sample, follow their voice.

First identify the questions, understanding, evidence, and unresolved points in the source material. These guidelines apply to learning notes and technical blogs. Do not extend them to interface specifications, incident reports, or every conversation.

- **Position the author and reader.** When the conversation establishes a learning context, acknowledge it in the author's voice. Use first-person singular for the author's actual questions and judgments, and first-person plural to invite the reader to reason together. Vary paragraph openings. Do not invent experiences, feelings, or conclusions.
- **Follow the process of understanding.** Start with a problem, explain its causes, and introduce concepts, categories, or boundaries as they become useful. Explain how adjacent paragraphs connect. Preserve the transition from the broad picture to specific details. Avoid repeatedly describing the article's purpose, selection of material, or analytical procedure. Do not impose one fixed paragraph sequence.
- **Enter the discussion directly.** Introduce a concrete example, then explain its goal, approach, and difficulties. Avoid editorial announcements such as "This article uses the same example throughout" or "The example is used to analyze design requirements." Connect questions and answer them as the discussion develops. Adding pronouns or question marks alone does not create a narrative.
- **Explain the unfamiliar through the familiar.** Choose examples the reader can understand without knowing the concept being introduced. To introduce agents, use a task such as researching compression techniques. An agent's memory architecture would require concepts the reader has yet to learn. Once a concept has been introduced, examples within it can be useful.
- **Derive a new system from an existing one.** When explaining a system design or replacement, describe how an existing system performs the same task. Explicitly introduce the proposed replacement. Use the relationship to identify reusable experience, mechanisms that need adaptation, and problems caused by changed conditions. The existing system may be a human workflow, software, or an organization. Human behavior is not a universal template. Keep using the example in the reasoning that follows. Transfer only relationships that hold; do not assume the new system inherits the old system's abilities or force a counterpart for every new mechanism.
- **Keep useful transitions.** Phrases such as "From a broad perspective," "In this case," or "Let us first look at" can clarify how the explanation advances. Keep them when they serve that purpose. Remove empty announcements of what comes next without stripping away every transition.
- **Let sentences develop naturally.** Related clauses can share a sentence. Vary sentence length with the explanation. Avoid mechanical word-count splits, deliberately choppy prose, slogans, or theatrical rhetorical questions added to sound human.
- **Explain in paragraphs first.** Use connected prose for relationships that need explanation. Tables work for comparing concepts, parameters, or data; numbered lists work for genuinely ordered steps. When replacing a table, carry its useful information into the prose. Editing the style must preserve technical conditions.
- **Clean up dictated text while preserving connections.** Remove verbal fillers, repeated starts, and transcription errors by default. Preserve the user's tone and reasoning. Keep fillers when the user explicitly requests them, and do not add conversational tics to simulate a voice.
- **State factual boundaries naturally.** Introduce hypothetical examples as hypothetical. There is no need to append "not implemented or tested" to each one. For actual experiments and claimed effects, state what was done, what evidence exists, and what remains unverified. Preserve the meaning of terminology, code, assumptions, and citations.

## Voice Reference

The author approved a Chinese opening with the following meaning and progression. This English rendering illustrates the perspective and rhythm:

> When designing an agent, we first need to clarify what it should accomplish, what it may do, and how we will check the result. This is the first entry in my systematic study of agents, so we will begin with those questions. From a broad perspective, agent design involves execution orchestration, memory management, and tool use, as well as collaboration between multiple agents. We will explore specific implementations and related papers in later entries.

Use the sample to calibrate the author's perspective, sentence rhythm, and transition from overview to detail. Do not reuse it as a mandatory opening, mechanically add first-person pronouns, copy its sentence patterns, or force the same example into every article.

## Review

Read adjacent paragraphs together. Check whether they develop a question or repeatedly restart a list of requirements. Remove repeated navigation and unsupported grand conclusions. Preserve technical conditions, citations, and uncertainty. Follow the user's latest explicit preferences when they provide new samples or corrections.

For explanations involving an existing and a proposed system, check that the transition is explicit, the later reasoning actually uses the earlier experience, and the limits of the analogy are clear.
