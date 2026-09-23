---
source_id: topic-tool-calling
title: Tool and function calling
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Tool and function calling

Illustrative text for a demo system; not official CamTech policy.

## What a tool is

A tool is a registered function with a name, a description, and a schema for its arguments. A model or a router proposes a call; the application validates the arguments and runs the function; the result goes back into the conversation as data.

## Selection is not execution

Proposing a tool call and running it are separate steps. Only registered code runs, and only after argument validation. A proposed tool name that is not in the registry is rejected.

## Identity comes from the session

A tool that reads personal records takes the account from the session, never from an argument that a model fills. Otherwise a message such as a request for another account's records could be turned into a valid call.

## Errors are data

A failed lookup returns a structured error, for example `{"ok": false, "error": "timeout"}`, instead of raising an exception. The workflow can then retry, explain, or choose another path.

## Read and write tools

Read tools look up facts. Write tools change state, such as booking a room. Write tools always pass a risk gate and wait for an explicit confirmation before they run.

## Database tools

Parameterised query templates are safe and predictable. Text-to-SQL is flexible but needs a sandbox: a read-only connection, an allow-list of tables and columns, and a row cap.
