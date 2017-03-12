## helper functions for generating probability distributions for component scores as part of CMS 2.0.
## last updated: 03.12.17 vitti@broadinstitute.org

import os, subprocess

def write_bin_paramfile(readfilename, writefilename, bounds):
	'''given an inclusive cosi sweep parameter file, writes another with stricter final frequency rejection criteria'''
	readfile = open(readfilename, 'r')
	writefile = open(writefilename, 'w')
	foundSweep = False
	for line in readfile:
		if "sweep_mult" not in line:
			writefile.write(line)
			foundSweep = True
		else:
			writestring = ""
			entries = line.split()
			for ientry in range(len(entries) - 1):
				writestring += str(entries[ientry]) + " "
			writestring += str(bounds[0]) + '-'+str(bounds[1]) +'\n'
			writefile.write(writestring)
	readfile.close()
	writefile.close()
	if foundSweep == False:
		print("ERROR: did not find sweep parameters in inputfile.")
	return
def run_traj(output, cosibuild, params, maxAttempts=100):
	commandstring = "env COSI_NEWSIM=1 COSI_MAXATTEMPTS=" + str(maxAttempts) + " COSI_SAVE_TRAJ=" + output + " " + cosibuild + " -p " + params + " --traj-only"   
	print(commandstring)

	itWorked, nAttempts = False, 0

	while itWorked == False:
		nAttempts +=1
		try:
			subprocess.check_output(commandstring.split())
		except:
			continue
		itWorked = True	

	print("found a trajectory in " + str(nAttempts) + " attempts.")
	assert os.path.isfile(output)
	return
###################
### SELFREQ BINS ##
###################
def get_bin_strings(bin_medians):
	'''given input bin medians, returns minimal len strs needed to create unique bin labels'''
	stringlen = 3 #minimum is '0.x' -- not necessarily the most descriptive way to round these, but it's functional.
	unique = False
	bin_medians_rewritten = ["%.2f" % a for a in bin_medians]
	return bin_medians_rewritten
def get_bins(freqRange=".05-.95", numbins=9):
	fullrange = [float (x) for x in freqRange.split('-')]
	binlen = (fullrange[1] - fullrange[0]) / float(numbins)
	bin_starts = [fullrange[0] + binlen*i for i in range(numbins)]
	bin_ends = [fullrange[0] + binlen*i for i in range(1,numbins+1)]
	bin_medians = [(float(bin_starts[i]) + float(bin_ends[i]))/2. for i in range(len(bin_starts))]
	bin_medians_str = get_bin_strings(bin_medians)
	return fullrange, bin_starts, bin_ends, bin_medians, bin_medians_str	
def check_bin_filled(directory, numsims):
	'''counts all non-empty files in directory, returns True if >= numsims'''
	filenames = os.listdir(directory)
	nonempty = [x for x in filenames if check_file_len(x) !=0]
	if len(filenames) < numsims:
		return False
	else:
		return True

##################
### BOOKKEEPING ##
##################
def check_create_dir(directory):
	""" ensure that the directory exists; create it if it doesn't """
	if not os.path.isdir(directory):
		subprocess.check_output(['mkdir', '-p', directory])
	return
def check_file_len(filename):
	'''counts number of lines in file'''
	if os.path.isfile(filename) and os.path.getsize(filename) > 0:
		openfile = open(filename, 'r')
		iline = 0
		for line in openfile:
			iline +=1
		openfile.close()
		return iline
	else:
		return 0
def check_create_file(filename, checkOverwrite):
	""" useful to prevent overwriting, but easy to toggle in case one wants to mass-replace files """
	if checkOverwrite == False:
		return True #make it anyway
	else:
		if not os.path.isfile(filename) or os.path.getsize(filename) == 0:
			return True
		else:
			return False
	return False
def execute(commandstring):
	subprocess.check_output(commandstring.split())
	return
def get_concat_files(model, pop, score, altpop = '', basedir = "/idi/sabeti-scratch/jvitti/clean/scores/"):
	""" locates concatenated component score files to facilitate normalization to neutral replicates """
	if score in ['ihs', 'delihh', 'nsl']:
		concatfilebase = basedir + model + "/neut/concat_" + str(pop) + "_"
	elif score in ['xpehh', 'fst']:
		concatfilebase = basedir + model + "/neut/concat_" + str(pop) + "_" + str(altpop) + "_"
	else:
		concatfilebase = ""
	concatfilename = concatfilebase + score + ".txt"
	binfilename = concatfilebase + score + ".bins"
	return concatfilename, binfilename