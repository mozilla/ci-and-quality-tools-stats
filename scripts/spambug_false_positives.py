from bugbug import db, bugzilla

db.download(bugzilla.BUGS_DB)

def search_false_positives():
    counter = 0
    for bug in bugzilla.get_bugs():
        for transaction in bug['history']:
            if transaction['who'] == 'release-mgmt-account-bot@mozilla.tld' and bug['resolution'] != 'INVALID':
                for change in transaction['changes']:
                    if change['field_name'] == 'resolution' and change['added'] == 'INVALID' and bug['resolution'] != 'INVALID':
                        print(f"Bug ID: {bug['id']}")   
                        counter += 1
                        break
    return counter

if __name__ == "__main__":
    db.download(bugzilla.BUGS_DB)
    counter = search_false_positives()
    print(f"Number of bugs marked as false positives: {counter}")