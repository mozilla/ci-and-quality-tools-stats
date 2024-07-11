from bugbug import db, bugzilla


# def search_correct_spam():
#     counter = 0
#     for bug in bugzilla.get_bugs():
#         for transaction in bug['history']:
#             if transaction['who'] == 'release-mgmt-account-bot@mozilla.tld' and bug['resolution'] == 'INVALID':
#                 for change in transaction['changes']:
#                     if change['field_name'] == 'resolution' and change['added'] == 'INVALID':
#                         print(f"Bug ID: {bug['id']}")   
#                         counter += 1

#     return counter
def search_correct_spam():
    comment_text = """If you think the bot is wrong, please reopen the bug and move it back to its prior component."""

    counter = 0
    for bug in bugzilla.get_bugs():
        for comment in bug['comments']:
            if comment_text in comment['text']:
                print(f"Bug ID: {bug['id']}")
                counter += 1

    return counter
if __name__ == "__main__":
    # db.register(
    #     bugzilla.BUGS_DB,
    #     "https://community-tc.services.mozilla.com/api/index/v1/task/project.bugbug.data_bugs.latest/artifacts/public/bugs.json.zst",
    #     10
    # )
    # db.download(bugzilla.BUGS_DB)
    counter = search_correct_spam()
    print(f"Number of bugs marked as spam: {counter}")