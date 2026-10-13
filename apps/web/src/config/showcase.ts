export interface ShowcaseCategory {
  slug: string;
  name: string;
  description: string;
  sampleTopics: readonly string[];
}

export const showcaseCategories = [
  {
    slug: "education",
    name: "Education",
    description: "Science, history and maths explained step by step for learners of every age.",
    sampleTopics: ["How photosynthesis works", "Why the sky is blue", "The Pythagorean theorem"],
  },
  {
    slug: "frontend",
    name: "Frontend",
    description: "Browsers, rendering and the frameworks that build modern interfaces.",
    sampleTopics: ["How the event loop works", "What React Server Components are"],
  },
  {
    slug: "backend",
    name: "Backend",
    description: "APIs, databases and the services that run behind every app.",
    sampleTopics: ["How database indexes work", "REST versus GraphQL"],
  },
  {
    slug: "system-design",
    name: "System Design",
    description: "Scaling, caching and the trade-offs behind large systems.",
    sampleTopics: ["How a CDN speeds up a website", "Designing a rate limiter"],
  },
  {
    slug: "devops",
    name: "DevOps",
    description: "Containers, pipelines and the practice of shipping software safely.",
    sampleTopics: ["What a container really is", "Blue-green deployments"],
  },
  {
    slug: "applied-ai",
    name: "Applied AI",
    description: "Practical AI: prompting, retrieval and agents that do useful work.",
    sampleTopics: ["What retrieval-augmented generation is", "How embeddings capture meaning"],
  },
  {
    slug: "machine-learning",
    name: "Machine Learning",
    description: "Models, training and the maths that makes them learn.",
    sampleTopics: ["How gradient descent works", "Overfitting explained"],
  },
  {
    slug: "cybersecurity",
    name: "Cybersecurity",
    description: "Threats, defences and how to keep systems and people safe.",
    sampleTopics: ["How HTTPS keeps you safe", "What a CSRF attack is"],
  },
  {
    slug: "blockchain",
    name: "Blockchain and Web3",
    description: "Ledgers, consensus and smart contracts without the hype.",
    sampleTopics: ["How a blockchain reaches consensus", "What a smart contract is"],
  },
] as const satisfies readonly ShowcaseCategory[];
