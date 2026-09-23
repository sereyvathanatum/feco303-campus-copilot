---
source_id: topic-mcp
title: The Model Context Protocol
language: en
licence: CC-BY-4.0 (written for this pack)
---
# The Model Context Protocol

Illustrative text for a demo system; not official CamTech policy.

## Purpose

The Model Context Protocol (MCP) is an open protocol for connecting AI applications to tools and data. An MCP server exposes tools, resources, and prompts; an MCP client inside the application discovers and calls them.

## Tools and resources

Tools are functions with JSON schemas, like the tools of a function-calling API. Resources are readable items identified by URIs, such as documents. A server declares both, so any compatible client can use them without custom integration code.

## Transports

A local server usually runs as a subprocess and talks over standard input and output (stdio). Remote servers use HTTP-based transports. The transport changes how messages travel, not what the tools do.

## Trust boundaries

A server decides what it exposes. Exposing only read tools over MCP keeps write actions inside the application, behind its confirmation gate. Tool descriptions and results coming from a server are untrusted input for the model.

## Testing

The same tool-contract tests can run against in-process tools and against the MCP transport. Identical results show that the protocol layer changed nothing. The MCP Inspector lists a server's tools and runs single calls by hand.
