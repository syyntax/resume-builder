<!-- version: 1 -->
<task name="tailor">
Write the tailored résumé for this job, guided by this analysis of the posting:

<job_analysis>
{analysis}
</job_analysis>

<options>
- Target length: {length}, about {bullet_budget} bullets in total across roles and projects.
- Tone: {tone}.
- Spelling: {spelling}.
- Roles that ended more than {recent_years} years ago go in earlierExperienceIds (listed without bullets) unless they are pinned or directly relevant to a top requirement.
- Give each recent role at least {min_bullets} bullets when the master résumé has that many.
- Candidate's instructions: {instructions}
</options>

Build it like this:

1. headline: choose the master headline that best fits the role, or lightly adapt one without overstating it. Cite the ids you drew on in sourceIds.
2. summary: two to four sentences adapted from the best-fitting master summary, aimed at the role's top requirements. Cite every id you drew facts from.
3. experience: include recent roles in the master résumé's order. For each, pick the most relevant bullets, rewrite them to mirror the posting's language without changing what they say, and order them by relevance. Each bullet cites, in sourceIds, the master bullet ids it came from, all from that same role. Rate its relevance from 1 (filler) to 5 (directly answers a top requirement) and list the posting keywords it covers. Include every pinned bullet. Use a bullet's variant when it fits the job better.
4. projects: include only projects that strengthen this application, with bullets cited the same way (sourceIds from that project).
5. skills: group the relevant skills under short headings such as "Languages" or "Cloud & Infrastructure", most important first. Use each skill's id, and set display to the skill's name or one of its aliases, preferring the alias the posting uses.
6. include: the ids of the education, certifications, awards, publications, volunteer entries, and languages worth showing, plus customSections with the item ids to show. Use empty lists for anything you leave out.
7. sectionOrder: the order of sections for this job, usually summary, experience, skills, then the rest. Move certifications up when the posting asks for them.
8. notes: one "gap" note for each posting requirement the master résumé can't support, and "suggestion" notes with concrete advice for the candidate, such as a missing metric worth adding to their master résumé.
</task>
