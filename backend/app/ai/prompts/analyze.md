<!-- version: 1 -->
<task name="analyze">
Analyze the job posting and compare it with the candidate's master résumé.

1. Record the company, job title, location or remote policy, and employment type when the posting states them; use null when it doesn't. Set seniority to the level the role is pitched at, or "unknown".
2. Summarize the role in two or three sentences: what this person will own and why the role exists.
3. List the requirements as separate, atomic items, with ids r1, r2, and so on. Mark each "required" or "preferred" (nice to have, bonus, plus) and give it the keywords it hinges on.
4. Extract the keywords a recruiter or ATS would screen for: technologies, tools, methods, domain terms, certifications, and the soft skills the posting stresses. Use the posting's spelling as `term`, list common alternative spellings or abbreviations as `aliases`, and rate importance: 3 for central, repeated, or required; 2 for clearly wanted; 1 for mentioned in passing. Aim for 10 to 30 keywords. Set `mustInclude` to false.
5. List up to 8 main responsibilities, and up to 6 company signals: what the posting itself says about the team's values, product, mission, or culture.
6. For every requirement, judge the candidate's match as "met", "partial", or "missing". Give the ids of the master résumé items that serve as evidence (roles, bullets, projects, skills, certifications) and a short note. Be honest: "missing" is more useful to the candidate than a stretch.
7. Rate the overall fit as strong, moderate, or weak, with a short rationale, and suggest three to five themes the résumé should emphasize.
</task>
