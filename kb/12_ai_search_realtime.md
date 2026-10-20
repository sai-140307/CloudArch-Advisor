# Adding AI, search and real-time features

## Generative AI features
Amazon Bedrock offers foundation models through one API without managing servers. Retrieval-Augmented Generation (RAG) grounds model answers in your own documents to reduce hallucination: documents are chunked, embedded, stored in a vector index, retrieved by similarity and added to the prompt. Use Bedrock Guardrails to filter unsafe content. Watch token costs and cache repeated answers.

## Search
Amazon OpenSearch Service provides full-text search, filtering and log analytics. It runs on always-on nodes, so it has a fixed monthly cost; for small catalogues, DynamoDB or Aurora queries may be enough.

## Real-time streaming
Amazon Kinesis Data Streams ingests ordered streams of events such as clickstreams, IoT telemetry and live game events. For simple fan-out of notifications use SNS, and for decoupling work use SQS.
