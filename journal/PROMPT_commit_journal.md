# Commit Journal Entry Prompt

Use this prompt to generate journal entries for git commits in your writing style.

---

## Prompt Template

```
I need you to create a technical journal entry for a specific git commit. Ensure that you get the full commit message for your context when accessing git hub. Ensure that you only access one day of commits at a time. Ensure that each journal entry collects all the commit context for that day.

Do not do one journal entry for each commit. (unless there is only one commit that day)

WRITING STYLE REFERENCE:
- Review @journal/writing_samples.md for my personal writing style
- Mix my reflective, introspective style with clear technical communication
- Be concise but not dry - include both technical details and personal reflection
- Use plain English for narrative, but keep technical terms precise
- Focus on what actually happened and what it means

COMMIT TO DOCUMENT:
[Paste the git commit hash or describe which commit]

REQUIRED STRUCTURE:
1. Title (# descriptive title)
2. Date (bold format: **Month DD, YYYY**)
3. Tags (hashtags like: #moritrac #bug-fix #feature-name #technology-used)
4. Horizontal rule (---)
5. Opening paragraph (what was done, why it matters)
6. Technical section (## The Problem / ## What Changed / ## The Fix)
   - Clear explanation of the technical work
   - Actual code/file changes mentioned
   - Specific details (numbers, file names, functions)
7. Testing/Results section (what was tested, how we verified)
8. Closing reflection (what this means, lessons learned, fears/concerns)

FORMAT:
- Save as: journal/YYYY-MM-DD_descriptive_slug.md
- Keep it under 120 lines total
- Include horizontal rules between sections
- No excessive whitespace

TONE:
- Honest about uncertainty and mistakes
- Aware of the weight of building healthcare software
- Technical but not sterile
- Reflective but not verbose

Get the commit details using git commands, then write the entry.
```

---

## Quick Usage

When you want to journal a commit:

1. Get the commit hash: `git log -1 --oneline` (or specific hash)
2. Get commit details: `git show <hash>`
3. Paste the prompt template above to your AI
4. Specify which commit to document
5. Review and save the generated entry

## Example Tags by Topic

**Bug Fixes:** `#bug-fix #data-loss #merge-failure #silent-error`
**Features:** `#feature #patient-dashboard #FHIR #document-processing`
**Infrastructure:** `#PostgreSQL #Docker #Celery #database-migration`
**Testing:** `#testing #unit-tests #integration-tests #test-coverage`
**Security/Compliance:** `#HIPAA #encryption #PHI #audit-logging #security`
**AI/LLM:** `#LLM #Claude #GPT #AI-integration #prompt-engineering`
**Performance:** `#performance #optimization #caching #indexing`
**Refactoring:** `#refactor #code-quality #technical-debt #cleanup`
**Documentation:** `#docs #documentation #README #comments`

---

*Keep writing. Keep reflecting. Keep building.*

