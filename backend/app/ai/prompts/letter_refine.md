<!-- version: 1 -->
<task name="letter_refine">
The candidate is editing their cover letter and asked for a change. Make only that change.

<job_analysis>
{analysis}
</job_analysis>

<user_notes>
{notes}
</user_notes>

<current_letter>
{letter}
</current_letter>

<request>
Target: {target}
Instruction: {instruction}
</request>

The instruction and notes come from the candidate. Follow the instruction as far as the truthfulness rules allow; statements about the company may come only from the posting or the user notes.

Return in `paragraphs` the rewritten paragraphs, each with `targetId` set to the paragraph id it replaces (p1, p2, …), or "" for a new paragraph. When the target is the whole letter, return the complete new letter in order. Cite `sourceIds`, `jobRefs` and `companySources` for each paragraph as in the original. Don't include a salutation, closing line or signature. Use `notes` to explain anything you couldn't do.
</task>
