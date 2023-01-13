# %%
# Generate events for bug from the Bugzilla
from enum import Enum, auto
from bugbug import db, bugzilla


class Stage(Enum):
    NOTHING = auto()
    NO_COMPONENT = auto()
    UNCONFIRMED = auto()
    CONFIRMED = auto()
    TRIAGED = auto()
    ASSIGNED = auto()
    IN_REVIEW = auto()
    RESOLVED = auto()

    def __lt__(self, other):
        return self.value < other.value

    def __str__(self) -> str:
        return self.name.capitalize().replace("_", " ")


current_status = {stage: 0 for stage in Stage}
events = []


def status_to_stage(status):
    if status == "UNCONFIRMED":
        return Stage.UNCONFIRMED
    if status in ("NEW", "REOPENED"):
        return Stage.CONFIRMED
    if status == "ASSIGNED":
        return Stage.ASSIGNED
    if status == "REVIEW":
        return Stage.IN_REVIEW
    if status in ("RESOLVED", "VERIFIED", "CLOSED"):
        return Stage.RESOLVED

    raise ValueError(f"Unknown status `{status}`")


def get_current_stage(bug):
    stage = status_to_stage(bug["status"])

    if stage != Stage.RESOLVED:
        if any(attachment["is_patch"] for attachment in bug["attachments"]):
            return Stage.IN_REVIEW

        if bug["severity"] not in ("n/a", "--"):
            return Stage.TRIAGED

    return stage


start_date = "2022-01-01"

db.download(bugzilla.BUGS_DB)
for bug in bugzilla.get_bugs():
    if bug["type"] != "defect":
        continue

    if bug["last_change_time"] < start_date:
        current_status[get_current_stage(bug)] += 1
        continue

    is_confirmed_after_open = False
    is_severity_changed = False
    moved_to_component_at = None
    first_patch_at = None
    bug_events = []

    # Get changes in the status field
    for event in bug["history"]:
        for change in event["changes"]:
            if change["field_name"] == "status":
                bug_events.append(
                    (
                        event["when"],
                        status_to_stage(change["added"]),
                    )
                )
                if change["removed"] == "UNCONFIRMED":
                    is_confirmed_after_open = True

            elif (
                is_severity_changed
                and change["field_name"] == "severity"
                and change["added"] not in ("n/a", "--")
            ):
                is_severity_changed = True
                bug_events.append(
                    (
                        event["when"],
                        Stage.TRIAGED,
                    )
                )
            elif (
                moved_to_component_at is None
                and change["field_name"] == "component"
                and change["added"] != "Untriaged"
            ):
                moved_to_component_at = event["when"]

    # Get the date for the first patch
    for attachment in bug["attachments"]:
        if not attachment["is_patch"]:
            continue
        if first_patch_at is None or attachment["creation_time"] < first_patch_at:
            first_patch_at = attachment["creation_time"]
    if first_patch_at:
        bug_events.append((first_patch_at, Stage.IN_REVIEW))

    if moved_to_component_at:
        bug_events.append(
            (
                bug["creation_time"],
                Stage.NO_COMPONENT,
            )
        )
        bug_events.append((moved_to_component_at, Stage.IN_COMPONENT))

    elif is_confirmed_after_open:
        bug_events.append(
            (
                bug["creation_time"],
                Stage.UNCONFIRMED,
            )
        )
    else:
        bug_events.append(
            (
                bug["creation_time"],
                Stage.CONFIRMED,
            )
        )

    # Add the bug events to the final list
    bug_events.sort()
    last_stage = Stage.NOTHING
    for when, stage in bug_events:
        if stage > last_stage:
            events.append((when, stage, last_stage))
            last_stage = stage

events.sort()

# %%
# Aggregate te events by day
day_status = current_status.copy()
last_day = None

status_by_day = {stage: [] for stage in day_status}
dates = []

last_day = start_date
for when, stage, last_stage in events:
    day = when[:10]
    if day > last_day:
        last_day = day
        dates.append(day)

        for stage, num in day_status.items():
            status_by_day[stage].append(num)

    day_status[stage] += 1
    day_status[last_stage] -= 1


# %%
# Plot the results
import matplotlib.pyplot as plt
import numpy as np

plt.style.use("seaborn-v0_8-whitegrid")


labels = sorted(
    [stage for stage in status_by_day if stage != Stage.NOTHING], reverse=True
)
x = np.array(dates).astype(np.datetime64)
y = np.vstack(status_by_day[stage] for stage in labels)

fig, ax = plt.subplots()
ax.stackplot(x, y, labels=labels, alpha=0.8)
ax.legend(bbox_to_anchor=(1.32, 0.5), loc="center right")
ax.set(
    xlim=(x[0], x[-1]),
    title="Workflow for defect bugs from bugbug",
    ylabel="Number of Bugs",
)
ax.tick_params(axis="x", labelrotation=40)
fig.show()
# %%
