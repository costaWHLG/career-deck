# CareerDeck — Your Job Search Cockpit (built on OfferPilot)

[简体中文](README.md) | [English](README.en.md)

**From job discovery to offer decisions: a local-first personal opportunity manager.**

CareerDeck builds on [OfferPilot](https://github.com/offercontext/offerPilot)
by offercontext, keeping its application/resume/interview/offers capabilities and
adding a **job discovery layer**: multi-source ingestion, AI seven-dimension scoring,
and one-click promotion into the tracking pipeline. Personal resumes and preferences
are imported at first use and never shipped with this repository.

---

Upstream OfferPilot product description (base capabilities):

OfferPilot by offercontext is a local-first workspace for individual
job seekers. Keep applications, resumes, interviews and offers together,
with optional AI assistance for preparation and review.

## Features

| Feature | Purpose |
| --- | --- |
| Application tracking | Organize companies, roles, application stages and interview schedules |
| Resume management | Maintain resume versions and review job-specific material suggestions |
| Mock interviews | Practice with your resume and job description, then review feedback |
| Interview reviews | Record lessons and select priorities for further practice |
| Offer comparison | Compare compensation, benefits and response deadlines |
| Salary negotiation preparation | Prepare questions and communication drafts |

## Getting started

Run OfferPilot locally with Docker or from source.

See the [installation instructions](README.md#快速开始)
and [user guide in Chinese](docs/product-manual/产品说明书.md).

Basic application tracking does not require AI configuration.

## Privacy and limitations

Workspace data is stored locally. AI features send relevant materials
to your configured model service and may incur provider fees.

OfferPilot does not automatically submit applications or message recruiters.
Review generated content before using it.

## License

See [LICENSE](LICENSE) and the
[third-party notices](README.md#许可证).
