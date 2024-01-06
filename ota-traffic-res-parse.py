'''
This script is to be used for parsing/compiling individual E24 LHM OTA iPerf Traffic testing results into
one, more readable file (a CSV).

Author: Rayyan Abdul-Wahhab
'''

import os
import sys
import csv
import re
import json
import functools
import argparse

def normalizeHeader(testHeader):
    normalizedHeader = re.sub("TEST ", "", testHeader)
    normalizedHeader = re.sub(" :: ", ",", normalizedHeader)
    normalizedHeader = re.sub("[M|K|G|m|k|g], from", ",", normalizedHeader)
    normalizedHeader = re.sub("(\w+\s*)+-", "", normalizedHeader)
    normalizedHeader = re.sub("PORT|\.\.\.", "", normalizedHeader)
    normalizedHeader = re.sub(" to ", ",", normalizedHeader)
    return normalizedHeader


def parseResultsFromFile(resfile):
	# Test No., Target Server, IP version, Protocol, UL/DL, From (IP), To (IP), Port, IPGW, Outroute, Bandwidth (Mbps), Throughput (Mbps)
    rows = []

    print(f"=== Parsing {resfile}")
    with open(resfile) as f:
        contents = f.readlines()

    contentsStr = "".join(contents)

    # Get Date/Timestamp from filename
    [dateStr, timeStr] = re.sub(r".log", "", os.path.basename(resfile)).split("_")[-2:]
    testDate = dateStr[4:6] + "/" + dateStr[6:] + "/" + dateStr[:4]
    testTime = timeStr[:2] + ":" + timeStr[2:4] + ":" + timeStr[4:]
    # TODO where to put date time???

    # this will get all test headers
    testHeaders = re.findall(r"TEST \d+ ::.+", contentsStr)
    # this will get all test bodies
    testBodies = re.split(r"-{10,}\nTEST \d.+\n-{10,}", contentsStr)
    testBodies.pop(0) # first entry contains test info we don't need

    if len(testHeaders) != len(testBodies):
        print("WARNING: Number of test headers does not match number of test bodies! Possibly malformed results file given")
    else:
        print("Results file is well formed.")

    numTests = min(len(testHeaders), len(testBodies))

    print(f"=== Found {numTests} test results in file")

    for i in range(numTests):
        row = []
        testHeader = testHeaders[i]
        testBody = testBodies[i]
        if "speedtest.net" in testHeader:
            [
                testNo,
                testTarget,
                ipVer,
                ipgwID,
                outrouteID
            ] = list(map(lambda h: h.strip(), normalizeHeader(testHeader).split(",")))
            row = [testNo, testTarget, ipVer, "", "", "", "", "", ipgwID, outrouteID, "", ""]
            speedtestCLIResult = re.sub(r"\n*speedtest-cli.*\n", "", testBody).strip()

            # if speedtest CLI result is JSON formatted
            if re.search(r"--format json", speedtestCLIResult):
                if "{" in speedtestCLIResult:
                    speedtestJsonResult = re.sub(r"^.*\n", "", speedtestCLIResult).strip()  # remove first header line
                    speedtestResult = json.loads(speedtestJsonResult)
                    # Convert the result from Bytes per sec -> Bits per sec
                    downloadMbps = round(speedtestResult["download"]["bandwidth"] * 8 * 0.000001, 2)
                    uploadMbps = round(speedtestResult["upload"]["bandwidth"] * 8 * 0.000001, 2)
                    row.append(f"Download: {downloadMbps} Mbps\nUpload: {uploadMbps} Mbps")
                else:
                    row.append("")
            else:
                row.append(speedtestCLIResult)
        else:
            [
                testNo,
                testTarget,
                upOrDown,
                ipVer,
                testProto,
                ipgwID,
                outrouteID,
                testPort,
                testBW,
                fromIp,
                toIp
            ] = list(map(lambda h: h.strip(), normalizeHeader(testHeader).split(",")))
            row = [testNo, testTarget, ipVer, testProto, upOrDown, fromIp, toIp, testPort, ipgwID, outrouteID, testBW]
            # Now we need to search for the test throughput
            iperfTestCompleted = re.search(r".+\n.+\n\niperf Done.", testBody)
            if iperfTestCompleted:
                iperfResults = iperfTestCompleted.group().split("\n")[:2] # the result is always in the last 2 lines before 'iperf Done'
                iperfReceiverResult = list(filter(lambda res: "receiver" in res, iperfResults))
                if len(iperfReceiverResult) == 0:
                    print(f"ERROR: Could not find final test throughput for Test {testNo}! Marking as DNF")
                    row.append("DNF") # Did Not Finish (error or otherwise)
                else:
                    iperfReceiverResult = iperfReceiverResult.pop()
                    testThroughput = catcher = ""
                    for token in iperfReceiverResult.split():
                        if "/sec" in token: # the Bitrate portion of the result
                            testThroughput = f"{catcher} {token}"
                            break
                        catcher = token
                    row.append(testThroughput)
            else:
                print(f"WARNING (DNF): {testHeader}")
                iperfTestCmd = re.search(r"iperf3.*\n", testBody)
                if iperfTestCmd:
                    print(f"iPerf command was -> {iperfTestCmd.group().strip()}")
                row.append("DNF") # Did Not Finish (error or otherwise)
        
        # Parse Terminal Pre and Post statistics from test body
        bodyTokens = re.split(r"\s*-{8,}\n|\s*-{8,}GET Terminal Stats-{8,}\n*", testBody)
        if len(bodyTokens) > 4:
            row.append("") # add empty cell to skip speedtest CLI column
            pretestStats = bodyTokens[1]
            posttestStats = bodyTokens[3]
            row.append(pretestStats)
            row.append(posttestStats)

        # Finished parsing test result from file. Now add it to our list
        rows.append(row)

    return rows

def accumulateRowsOfResults(accRows, resfile):
    resultsFromFile = parseResultsFromFile(resfile)
    return accRows + resultsFromFile

def uploadFile(filename):
    MAX_RETRIES = 10
    rc = 0

    for i in range(0, MAX_RETRIES):
        rc = os.system(f'curl -sk -F file=@{filename} -F "terminal=e24_ota" https://40.76.136.34/cgi-bin/uploadLogFile.cgi')
        print("")
        if rc == 0:
            print("Upload successful!")
            break
    
    if rc != 0:
        print('ERROR: Failed to upload file')

def parse_args():
    parser = argparse.ArgumentParser(description='E24 OTA Traffic Results Parsing Tool/Aggregator')
    parser.add_argument('device',help="The DeviceID of the HM")
    parser.add_argument('dir',help="The dir to look for traffic test result files for the HM")
    parser.add_argument('-o', '--outputFile',dest="outfile", help="The desired name of the output file")
    return parser.parse_args()

def main():
    '''
	Given a HM traffic tests results file, I parse it to create a CSV with each row containing the data
	for one test
	'''
    args = parse_args()

    print(f"=== Collecting Traffic Test results for {args.device}")
	
    # Get list of .log files in specified directory
    filelist = [resfile for resfile in os.listdir(args.dir) if args.device in resfile and ".log" in resfile]
    
    if len(filelist) == 0:
        print("No files found in {} to parse.".format(args.dir))
        sys.exit(1)

    print("============================")
    print("=== Parsing file(s) below:")
    print("============================")
    # Create relative path list from filenames
    filelist = list(map(lambda filename: os.path.join(args.dir, filename), filelist))
    print(*filelist, sep="\n")

    # Create output file
    fields = [
		"Test No.",
        "Target Server",
		"IP version",
        "Protocol",
		"UL/DL",
		"From (IP)",
		"To (IP)",
		"Port",
		"IPGW",
        "Outroute ID",
        "Bandwidth (Mbps)",
		"Throughput",
        "Speedtest CLI results",
        "Pre-Test Stats",
        "Post-Test Stats"
    ]

    # Parse output file
    rows = functools.reduce(accumulateRowsOfResults, filelist, [])
    print("=== Finished parsing results!")

    # Output CSV of results
    filename = args.outfile if args.outfile is not None else f"{args.device}_traffic_results.csv"

    print(f"=== Writing parsed results to file {filename}")
    with open(filename, 'w') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(fields)
        csvwriter.writerows(rows)
    
    # Upload results file to remote
    print("=== Uploading results file to Azure server")
    uploadFile(filename)


# MAIN
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e)
        print("Exiting!")
        sys.exit(1)
