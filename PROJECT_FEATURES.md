# Meridian — Project Features

Meridian is a policy intelligence and audit workspace for regulated organizations. It helps teams find conflicting rules and outdated guidance, answer policy questions with exact citations, and reconstruct what applied and what an office knew at a particular time. The prototype models two bank offices, Dhaka and Frankfurt.

## Source ingestion

- Upload text-based PDFs, import saved Slack messages, or monitor selected public Slack channels through a read-only connector.
- Preserve original source versions alongside trusted metadata such as policy authority, applicability, effective dates, and access permissions.
- Track queued, running, completed, and failed ingestion jobs, including processing warnings and stages. Open original PDFs or Slack messages at their cited passages.

## Policy conflict detection and review

- Flag contradictions, stale guidance, and gaps between policy and procedure.
- Apply deterministic checks to supported loan approval and record retention rules.
- Use model-assisted comparison to propose general-policy findings for human review. Findings include the relevant source quotations and versions.
- Search and filter the findings queue, then acknowledge, resolve, or dismiss findings with a recorded reason.

## Cited policy questions

- Ask plain-language questions across accessible sources or limit a question to one source version.
- Open exact citations in the original document or Slack message. Reopen saved answers and share them with authorized teammates.
- Show when available evidence is conflicting or incomplete, and abstain when the sources do not support an answer.

## Policy history and version control

- Track when a rule took effect separately from when the office learned about it. For example, ask what rule applied in January using only the information available at the end of that month.
- Compare document versions side by side, including changes to text and metadata. Explicit replacement links identify which earlier rules a new version supersedes.
- Withdraw a source from current use while keeping its original content, past citations, and review history available for audit.

## Evidence lineage and verification

- Trace findings and answers to their supporting statements, source passages, and document versions.
- Verify a PDF or saved Slack copy against the preserved original. File identity and text integrity are checked separately, so a metadata-only PDF change can be distinguished from a change to the text.
- Export signed answer bundles for independent verification of signatures and evidence bindings. These checks establish integrity and provenance. Reviewers assess the policy interpretation.

## Cross-office comparisons

- Ask the same question in Dhaka and Frankfurt and review the independently cited answers side by side.
- Run signed comparisons for supported numeric loan approval and record retention rules. The gateway exchanges approved structured claims while original documents stay with their respective offices.
- Show gaps in available evidence. Cross-office general-text comparison relies on human review of the two answers.

## Access control and audit

- Manage admin, reviewer, uploader, and reader privileges by office, with separate access controls for restricted sources.
- Review activity for source processing, publication, withdrawal, review decisions, and data transfers.

## Example workflow

A Slack message repeats an older loan approval rule. Meridian flags the message as stale against the newer policy. A reviewer opens both source passages, checks when the newer rule took effect, and records a decision with a reason.

See the [workspace guide](README.md#browser-workspace), [general policy guide](docs/general_policy_demo.md), and [Slack integration guide](docs/slack_integration.md) for details.
