# VB365 cleaner

This script is designed to remove either M365 SharePoint or Teams sites that have been deleted from the M365 environment but are still in Veeam Backup for M365 jobs.

It does this by looking at the current Teams and SharePoint sites in the M365 environment and comparing them to what is in the backup jobs. If it finds a site that is in the backup job but not in the M365 environment it will remove it from the backup job.

If it finds that the job only has that item in it, it will disable the job, you can then manually remove the job if you wish.

Note that this still needs further testing, use at your own risk.

Currently configured to work with Veeam Backup for M365 version 7.

UPDATE: 24/10/2023

Changes have been made so this no longer uses restore points as the reference for currently protected items. This has been moved to the job itself as that tracks the items even if there hasn't been a successful backup.

## Usage

You will need a config.json file with the following:

```json
{
  "username": "administrator@yourdomain.com",
  "vb365_address": "192.168.0.123"
}
```

The password needs to be set as an environment variable called `VB365_PASSWORD`.

To run the script in normal mode:

```powershell
python .\vb365_cleaner.py
```

If you wish to test the script, you can run it in dry-run mode:

```powershell
python .\vb365_cleaner.py --dry-run
```

All actions are logged into a log file called app.log.

## Requirements

You will need install the following dependencies:

- VeeamEasyConnect
- click

You can do this in a single command:

```powershell
pip install veeam_easy_connect click
```

## License

The script is provided under the MIT license. It is not supported by Veeam Support and comes with no warranty. Use at your own risk.
