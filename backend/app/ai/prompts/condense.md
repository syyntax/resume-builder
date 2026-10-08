<!-- version: 1 -->
<task name="condense">
These texts need to be shorter to fit on one page. {goal}

<texts>
{items}
</texts>

Return in `items` every text, each with `targetId` set to its id and `text` the shortened version. Shorten the longer texts more; leave a text unchanged if it's already brief.
</task>
