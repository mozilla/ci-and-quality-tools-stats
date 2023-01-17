# %%
# Generate events for bug from the Bugzilla
from enum import Enum, auto
from bugbug import db, bugzilla
import re

OLDEST_BUG = "2020-01-01"

NI_PAT = re.compile(r"needinfo\?\((.*?)\)")


class Stage(Enum):
    NOTHING = auto()
    NO_COMPONENT = auto()
    UNCONFIRMED = auto()
    CONFIRMED = auto()
    PENDING_NEEDINFO = auto()
    REMOVE_NEEDINFO = auto()
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


db.download(bugzilla.BUGS_DB)
for bug in bugzilla.get_bugs():
    if (
        bug["type"] != "defect"
        or bug["product"] == "Invalid Bugs"
        or bug["creation_time"] < OLDEST_BUG
    ):
        continue

    is_confirmed_after_open = False
    is_severity_changed = False
    is_moved_to_component_after_open = False
    first_patch_at = None
    bug_events = []

    current_needinfos = []
    needinfo_events = [
        {
            "time": bug["creation_time"],
            "add": [],
            "remove": [],
        }
    ]

    # Get stage changing events from the bug history
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

            elif change["field_name"] == "severity":
                if not is_severity_changed and change["added"] not in ("n/a", "--"):
                    is_severity_changed = True
                    bug_events.append(
                        (
                            event["when"],
                            Stage.TRIAGED,
                        )
                    )
            elif change["field_name"] == "component":
                if (
                    not is_moved_to_component_after_open
                    and change["added"] != "Untriaged"
                ):
                    is_moved_to_component_after_open = True
                    # If the bug was confirmed at this time, this even will be filtered out
                    bug_events.append((event["when"], Stage.UNCONFIRMED))
            elif change["field_name"] == "flagtypes.name":
                removed_needinfos = NI_PAT.findall(change["removed"])
                added_needinfos = NI_PAT.findall(change["added"])
                needinfo_events.append(
                    {
                        "time": event["when"],
                        "add": added_needinfos,
                        "remove": removed_needinfos,
                    }
                )
                for email in removed_needinfos:
                    try:
                        current_needinfos.remove(email)
                    except ValueError:
                        # This means that the needinfo was added at the creation time
                        needinfo_events[0]["add"].append(email)

                current_needinfos.extend(added_needinfos)

    # Add needinfos that was added at the creation time and still pending
    needinfo_events[0]["add"].extend(
        flag["requestee"]
        for flag in bug["flags"]
        if flag["name"] == "needinfo" and flag["requestee"] not in current_needinfos
    )

    # Convert needinfo events to stage events
    current_needinfos = []  # reset the list
    for event in needinfo_events:
        was_pending = len(current_needinfos) > 0
        for email in event["remove"]:
            current_needinfos.remove(email)
        current_needinfos.extend(event["add"])

        if was_pending and len(current_needinfos) == 0:
            bug_events.append(
                (
                    event["time"],
                    Stage.REMOVE_NEEDINFO,
                )
            )

        elif not was_pending and len(current_needinfos) > 0:
            bug_events.append(
                (
                    event["time"],
                    Stage.PENDING_NEEDINFO,
                )
            )

    # Get the date for the first patch
    for attachment in bug["attachments"]:
        if not attachment["is_patch"]:
            continue
        if first_patch_at is None or attachment["creation_time"] < first_patch_at:
            first_patch_at = attachment["creation_time"]
    if first_patch_at:
        bug_events.append((first_patch_at, Stage.IN_REVIEW))

    if is_moved_to_component_after_open or bug["component"] == "Untriaged":
        bug_events.append(
            (
                bug["creation_time"],
                Stage.NO_COMPONENT,
            )
        )
    elif is_confirmed_after_open or bug["status"] == "UNCONFIRMED":
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
        if stage is Stage.REMOVE_NEEDINFO:
            if last_stage is not Stage.PENDING_NEEDINFO:
                continue

            for event in reversed(events):
                if event[1] not in (Stage.PENDING_NEEDINFO, Stage.REMOVE_NEEDINFO):
                    stage = event[1]
                    break
                if event[2] is Stage.NOTHING:
                    raise Exception("No stage found for REMOVE_NEEDINFO")

        if stage > last_stage or last_stage is Stage.PENDING_NEEDINFO:
            # Ignore stages that go backwards
            events.append((when, stage, last_stage))
            last_stage = stage

    if last_stage == Stage.NO_COMPONENT and bug["component"] != "Untriaged":
        raise Exception("Bug cannot be in NO_COMPONENT stage and have a component")

events.sort()

# %%
# Aggregate te events by day

day_status = current_status.copy()
last_day = None

status_by_day = {stage: [] for stage in day_status}
dates = []

last_day = ""
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
    [
        stage
        for stage in status_by_day
        if stage not in (Stage.NOTHING, stage.REMOVE_NEEDINFO)
    ],
    reverse=True,
)
x = np.array(dates).astype(np.datetime64)
y = np.vstack(status_by_day[stage] for stage in labels)

first_date = np.datetime64("2022-06-01")
first_date_idx = np.where(x == first_date)[0][0]
min_y_value = y[0][first_date_idx] - 1000

fig, ax = plt.subplots()
ax.stackplot(x, y, labels=labels, alpha=0.8)
ax.legend(bbox_to_anchor=(1.35, 0.5), loc="center right")
ax.set(
    ylim=(min_y_value, None),
    xlim=(first_date, x[-1]),
    title=f"Workflow for defect bugs created since {OLDEST_BUG}",
    ylabel="Number of Bugs",
)
ax.tick_params(axis="x", labelrotation=40)
fig.show()
# %%
