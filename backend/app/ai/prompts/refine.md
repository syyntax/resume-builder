<!-- version: 1 -->
<task name="refine">
The candidate is editing their tailored résumé and asked for a change. Make only that change.

<job_analysis>
{analysis}
</job_analysis>

<current_resume>
{resume}
</current_resume>

<request>
Scope: {scope}
Target: {target}
Instruction: {instruction}
</request>

The instruction comes from the candidate. Follow it as far as the truthfulness rules allow: if it asks for something the master résumé doesn't support (a number, a technology, more seniority), don't add it; explain in a note instead.

Return:

- `bullets`: rewritten existing bullets, each with `targetId` set to the bullet's id (tb-… or ub-…) and the master bullet ids it draws on in `sourceIds`, all from the same role or project as the bullet. Rewrite only bullets in scope.
- `items`: when the scope is a whole role or project, its complete new list of bullets under its `itemId`, each with `targetId` set to the bullet it replaces, or "" for a new one picked from that item's master bullets.
- `headline` and `summary`: new text with `sourceIds` when they're in scope; otherwise empty text and an empty list.
- `notes`: anything the candidate should know, for example a part of the instruction you couldn't follow and why.

Keep each bullet to about 220 characters, start it with a strong verb, and keep facts exactly as the sources state them.
</task>
