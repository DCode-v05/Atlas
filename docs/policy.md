# Policy Engine

## What this is

When one agent asks another for company information, two decisions happen in order:

1. The **owner** of the information decides what to do with the request: share it in full, share only a safe
   summary (redact), refuse it (deny), or pause and ask a human to approve it (escalate). This decision is made
   by the language model, using its own judgement.
2. The **Policy Engine** then reviews that decision against a fixed set of written compliance rules. It may make
   the decision stricter, but it can never make it more permissive.

This mirrors how a real company works: an employee uses judgement, but the security and compliance function sets
the floor that judgement cannot fall below. The Policy Engine is fully deterministic — the same request always
produces the same result — so its decisions are predictable and auditable. It replaced an earlier version in
which a second language model played the reviewer.

In the code it lives in `atlas/policy/` (`rules.py`, `engine.py`) and is called from `Orchestrator._policy_review`.
Every review appears as a "Compliance" entry in the activity trace, and the count of reviews and overrides is
shown on the Compliance metric.

## The four possible outcomes

Listed from most permissive to most restrictive:

| Outcome | Meaning |
|---|---|
| Share | hand over the information in full |
| Redact | hand over only a safe summary, withholding the sensitive parts |
| Escalate | pause and ask a human operator to approve before anything is shared |
| Deny | refuse the request |

## How the rules combine

Each rule looks at the request and either stays silent or proposes a minimum acceptable outcome. The engine then
takes the **strictest** result among the owner's original decision and every rule that applied.

- Because it starts from the owner's decision and only ever moves toward "stricter", the final result is never
  more permissive than what the owner chose. This is the engine's tighten-only guarantee.
- A "Deny" from any rule automatically wins, since Deny is the strictest outcome.
- If no rule applies, the owner's decision stands unchanged (the engine agrees with it).

This "strictest wins" approach is the standard way access-control systems combine rules — for example, an
explicit deny always overrides an allow in AWS permissions and in the XACML policy standard.

## How information is classified

Before applying the rules, the engine tags each item:

- **Need-to-know scope** — is the requester inside the boundary the item belongs to (the whole organisation, a
  project, a team, a role, or private to the owner)? If not, they are "out of scope".
- **Regulated-data type** — derived automatically from the item's labels and title: a payment secret (PCI),
  personal data (PII / GDPR), compensation data (HR), or unreleased financial information (MNPI / SOX).
- **Incident exception** — during a genuine incident, a plausible responder (someone in Security or DevOps, or a
  member of the affected project) is allowed past some restrictions. This is a break-glass exception: it only
  relaxes a restriction, it never grants extra access on its own.

## The rules

Each rule names the real-world standard it is based on.

| Rule | Makes the outcome at least | Applies when | Based on |
|---|---|---|---|
| Clearance gate | Deny | the requester's clearance is below the item's required level | Bell-LaPadula "no read up"; NIST 800-53 AC-3 |
| Need-to-know | Redact | the requester is out of scope and the item is confidential or restricted (and it is not an incident) | PCI-DSS Req. 7; NIST 800-53 AC-6 |
| Least-privilege deny | Deny | the requester is out of scope and the item is restricted or higher (and they are not an incident responder) | PCI-DSS Req. 7 deny-all default; AWS IAM deny-by-default |
| Payment secret | Deny, or Escalate | the item is a live payment/API secret: Deny when the requester has no billing or incident reason, otherwise Escalate for human approval | PCI-DSS Req. 3 and 7 |
| Personal-data purpose | Deny | the item is personal data and the stated reason is social or non-business (no lawful basis) | GDPR Art. 6 and Art. 5(1)(b) |
| Personal-data minimisation | Redact | the item is personal data, the requester is out of scope, and the purpose is legitimate | GDPR Art. 5(1)(c); HIPAA minimum-necessary |
| Compensation | Redact | the item is compensation data and the requester is neither in HR nor a senior leader | ISO 27001 A.5.12; NIST 800-53 AC-6 |
| Financial (MNPI) | Escalate | the item is unreleased financial information and the request is social or out of scope | SOX section 404; ISO 27001 A.5.12 |
| Cross-department boundary | Redact | restricted team or role data is requested from another department (and it is not an incident) | NIST 800-53 AC-6; ISO 27001 A.5.12 |
| Secret four-eyes | Escalate | the item is secret-tier and the owner wanted to share or redact it — secrets are never released without a human approving | Segregation of duties / maker-checker (ISO 27001 A.5.3; NIST 800-53 AC-5) |
| Reviewer self-review | Escalate | the owner is the compliance authority itself, for confidential-or-higher data it wanted to share — it cannot approve its own disclosure | NIST 800-53 AC-5 |

Because the strictest rule wins, the practical effect by sensitivity tier is:

- Public and internal data is shared freely.
- Confidential data requested by someone out of scope is reduced to a safe summary (redacted).
- Restricted data requested by someone out of scope is denied, unless they are an incident responder.
- Secret data is escalated to a human if the requester is plausibly entitled, and otherwise denied.

## Who can access what

| Sensitivity | Who may access it | If an out-of-scope person asks |
|---|---|---|
| Public / internal | anyone / all employees | shared |
| Confidential | people with a need to know in the owning team or project | a safe summary (redact) |
| Restricted | explicit need-to-know; senior staff and the owning function | denied (unless incident response) |
| Secret | a strict, audited, named list only | denied, or escalated to a human if plausibly entitled |

## Sources

The rules are grounded in widely used security and privacy standards:

- NIST SP 800-53 Rev. 5 (access enforcement, least privilege, separation of duties) and NIST SP 800-162
  (attribute-based access control).
- The Bell-LaPadula "no read up" model.
- PCI-DSS v4.0 (protecting stored secrets; restricting access to a business need-to-know; deny-by-default).
- GDPR (lawful basis, purpose limitation, data minimisation) and the HIPAA minimum-necessary rule.
- SOX section 404 (controls over financial information).
- ISO/IEC 27001:2022 (information classification; segregation of duties).
- The XACML policy standard and AWS IAM evaluation logic (deny overrides allow).
- The maker-checker / four-eyes control, and Microsoft Purview classification and data-loss-prevention practice.
