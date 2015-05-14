'''
    SelScan: A program to calculate EHH-based scans for positive selection in genomes
    https://github.com/szpiech/selscan
'''

__author__ = "tomkinsc@broadinstitute.org"

# built-ins
import os, os.path, subprocess
import logging
import gzip
from datetime import datetime, timedelta

# intra-module dependencies
import tools, util.file
from util.vcf_reader import VCFReader
from util.call_sample_reader import CallSampleReader
from util.recom_map import RecomMap

#third-party dependencies
from Bio import SeqIO
import pysam
from boltons.timeutils import relative_time
import numpy as np

tool_version = '1.0.4'
url = 'https://github.com/szpiech/selscan/archive/{ver}.zip'

log = logging.getLogger(__name__)

class SelscanFormatter(object):

    @staticmethod
    def _moving_avg(x, prevAvg, N):
        return float( sum([int(prevAvg)] * (N-1)) + x) / float(N)

    @staticmethod
    def _build_variant_output_strings(chrm, idx, pos_bp, map_pos_cm, genos, ref_allele, alt_allele, ancestral_call, allele_freq):
        outputStringDict = dict()
        outputStringDict["tpedString"]     = "{chr} {pos_bp}-{idx} {map_pos_cm} {pos_bp} {genos}\n".format(chr=chrm, idx=idx, pos_bp=pos_bp, map_pos_cm=map_pos_cm, genos=" ".join(genos))
        outputStringDict["metadataString"] = "{chr} {pos_bp}-{idx} {pos_bp} {map_pos_cm} {ref_allele} {alt_allele} {ancestral_call} {allele_freq}\n".format(chr=chrm, idx=idx, pos_bp=pos_bp, map_pos_cm=map_pos_cm, ref_allele=ref_allele, alt_allele=alt_allele, ancestral_call=ancestral_call, allele_freq=allele_freq)

        return outputStringDict

    @staticmethod
    def _build_map_output_string(chrm, pos_bp, map_pos_cm):
        return "{chr} {pos_bp} {map_pos_cm} {pos_bp}\n".format(chr=chrm, pos_bp=pos_bp, map_pos_cm=map_pos_cm)

    @classmethod
    def process_vcf_into_selscan_tped(cls, vcf_file, gen_map_file, outfile_location,
        outfile_prefix, chromosome_num, samples_to_include=None, start_pos_bp=None, end_pos_bp=None, ploidy=2, consider_multi_allelic=True, include_variants_with_low_qual_ancestral=False, coding_function=None):
        """
            Process a bgzipped-VCF (such as those included in the Phase 3 1000 Genomes release) into a gzip-compressed
            tped file of the sort expected by selscan. 
        """
        processor = VCFReader(vcf_file)

        tabix_file = pysam.TabixFile(vcf_file, parser=pysam.asVCF())
        records = processor.records( str(chromosome_num), start_pos_bp, end_pos_bp, pysam.asVCF())

        end_pos = processor.clens[str(chromosome_num)] if end_pos_bp == None else end_pos_bp

        outTpedFile = outfile_location + "/" + outfile_prefix + ".tped.gz"
        outTpedMetaFile = outfile_location + "/" + outfile_prefix + ".tped.meta.gz"

        if samples_to_include is not None and len(samples_to_include) > 0:
            indices_of_matching_samples = sorted([processor.sample_names.index(x) for x in samples_to_include])
        else:
            indices_of_matching_samples = range(0,len(processor.sample_names))

        rm = RecomMap(gen_map_file)

        for filePath in [outTpedFile, outTpedMetaFile]:
            assert not os.path.exists(filePath), "File {} already exists. Consider removing this file or specifying a different output prefix. Processing aborted.".format(filePath)
            pass

        startTime = datetime.now()
        sec_remaining_avg = 0
        current_pos_bp = 1

        with util.file.open_or_gzopen(outTpedFile, 'w') as of1, util.file.open_or_gzopen(outTpedMetaFile, 'w') as of2:
            # WRITE header for metadata file here with selected subset of sample_names
            headerString = "CHROM VARIANT_ID POS_BP MAP_POS_CM REF_ALLELE ALT_ALLELE ANCESTRAL_CALL ALLELE_FREQ_IN_POP\n".replace(" ","\t")
            of2.write(headerString)

            recordCount = 0
            for record in records:
                
                if processor.variant_is_type(record.info, "SNP"):
                    alternateAlleles = [record.alt]
                    if record.alt not in ['A','T','C','G']:
                        #print record.alt
                        if consider_multi_allelic:
                            alternateAlleles = record.alt.split(",")
                        else:
                            # continue on to next variant record
                            continue

                    ancestral_allele = processor.parse_ancestral(record.info)
                    chromStr = "chr{}".format(record.contig)

                    # if the AA is populated, and the call meets the specified criteria
                    if (ancestral_allele in ['A','T','C','G']) or (include_variants_with_low_qual_ancestral and ancestral_allele in ['a','t','c','g']):
                        phased_genotypes_for_selected_samples = np.array( record[0:len(record)])[ indices_of_matching_samples ] #use numpy index array
                        genotypes_for_selected_samples = np.ravel(  [ list(x[::2]) for x in phased_genotypes_for_selected_samples] )

                        map_pos_cm = rm.physToMap(chromStr, record.pos)

                        numberOfHaplotypes = float(len(genotypes_for_selected_samples))
                        
                        for idx, altAllele in enumerate(alternateAlleles):
                            codingFunc = np.vectorize(coding_function)
                            coded_genotypes_for_selected_samples = codingFunc(genotypes_for_selected_samples,str(idx+1),record.ref,ancestral_allele,altAllele)

                            allele_freq_for_pop = float(list(coded_genotypes_for_selected_samples).count("1")) / numberOfHaplotypes

                            outStrDict = cls._build_variant_output_strings(record.contig, idx+1, record.pos, map_pos_cm, coded_genotypes_for_selected_samples, record.ref, altAllele, ancestral_allele, allele_freq_for_pop)
                            of1.write(outStrDict["tpedString"])
                            of2.write(outStrDict["metadataString"].replace(" ","\t"))

                        recordCount += 1
                        current_pos_bp = int(record.pos)

                        if recordCount % 1000 == 0:
                            number_of_seconds_elapsed = (datetime.now() - startTime).total_seconds()
                            bp_per_sec = float(current_pos_bp) / float(number_of_seconds_elapsed)
                            bp_remaining = end_pos - current_pos_bp
                            sec_remaining = bp_remaining / bp_per_sec
                            sec_remaining_avg = cls._moving_avg(sec_remaining, sec_remaining_avg, 10)
                            time_left = timedelta(seconds=sec_remaining_avg)
                        

                            if sec_remaining > 10:
                                human_time_remaining = relative_time(datetime.utcnow()+time_left)
                                print("Completed: {:.2%}".format(float(current_pos_bp)/float(end_pos)))
                                print("Estimated time of completion: {}".format(human_time_remaining))

class SelscanTool(tools.Tool):
    def __init__(self, install_methods = None):
        if install_methods == None:
            install_methods = []
            os_type                 = get_os_type()
            binaryPath              = get_selscan_binary_path( os_type    )
            binaryDir               = get_selscan_binary_path( os_type, full=False )
            
            target_rel_path = 'selscan-{ver}/{binPath}'.format(ver=tool_version, binPath=binaryPath)
            verify_command  = '{dir}/selscan-{ver}/{binPath} --help > /dev/null 2>&1'.format(dir=util.file.get_build_path(), ver=tool_version, binPath=binaryPath) 

            install_methods.append(
                    tools.DownloadPackage(  url.format( ver=tool_version ),
                                            target_rel_path = target_rel_path,
                                            verifycmd       = verify_command,
                                            verifycode      = 1 # selscan returns exit code of 1 for the help text...
                    )
            )

        tools.Tool.__init__(self, install_methods = install_methods)

    def version(self):
        return tool_version


    def execute_ehh(self, locus_id, tped_file, out_file, window, cutoff, max_extend, threads, maf, gap_scale):
        out_file = os.path.abspath(out_file)

        toolCmd = [self.install_and_get_path()]
        toolCmd.append("--ehh")
        toolCmd.append(locus_id)
        toolCmd.append("--tped")
        toolCmd.append(tped_file)
        toolCmd.append("--out")
        toolCmd.append(out_file)
        if window:
            toolCmd.append("--ehh-win")
            toolCmd.append(window)
        if cutoff:
            toolCmd.append("--cutoff")
            toolCmd.append("{:.6}".format(cutoff))
        if max_extend:
            toolCmd.append("--max-extend")
            toolCmd.append((max_extend))
        if threads > 0:
            toolCmd.append("--threads")
            toolCmd.append((threads))
        else:
            raise argparse.ArgumentTypeError("You must specify more than 1 thread. %s threads given." % threads)
        if maf:
            toolCmd.append("--maf")
            toolCmd.append("{:.6}".format(maf))
        if gap_scale:
            toolCmd.append("--gap-scale")
            toolCmd.append((gap_scale))

        toolCmd = [str(x) for x in toolCmd]
        log.debug(' '.join(toolCmd))
        subprocess.check_call( toolCmd )

    def execute_ihs(self, tped_file, out_file, threads, maf, gap_scale, skip_low_freq=True, trunc_ok=False):
        # --ihs --tped ./1out.tped.gz --out 1ihsout
        toolCmd = [self.install_and_get_path()]
        toolCmd.append("--ihs")
        toolCmd.append("--tped")
        toolCmd.append(tped_file)
        toolCmd.append("--out")
        toolCmd.append(out_file)
        if skip_low_freq:
            toolCmd.append("--skip-low-freq")
        if trunc_ok:
            toolCmd.append("--trunc-ok")
        if threads > 0:
            toolCmd.append("--threads")
            toolCmd.append((threads))
        else:
            raise argparse.ArgumentTypeError("You must specify more than 1 thread. %s threads given." % threads)
        if maf:
            toolCmd.append("--maf")
            toolCmd.append("{:.6}".format(maf))
        if gap_scale:
            toolCmd.append("--gap-scale")
            toolCmd.append((gap_scale))

        toolCmd = [str(x) for x in toolCmd]        
        log.debug(' '.join(toolCmd))
        subprocess.check_call( toolCmd )

    def execute_xpehh(self, tped_file, tped_ref_file, out_file, threads, maf, gap_scale, trunc_ok=False):
        toolCmd = [self.install_and_get_path()]
        toolCmd.append("--xpehh")
        toolCmd.append("--tped")
        toolCmd.append(tped_file)
        toolCmd.append("--tped-ref")
        toolCmd.append(tped_ref_file)
        toolCmd.append("--out")
        toolCmd.append(out_file)
        if trunc_ok:
            toolCmd.append("--trunc-ok")
        if threads > 0:
            toolCmd.append("--threads")
            toolCmd.append((threads))
        else:
            raise argparse.ArgumentTypeError("You must specify more than 1 thread. %s threads given." % threads)
        if maf:
            toolCmd.append("--maf")
            toolCmd.append("{:.6}".format(maf))
        if gap_scale:
            toolCmd.append("--gap-scale")
            toolCmd.append((gap_scale))

        toolCmd = [str(x) for x in toolCmd]
        log.debug(' '.join(toolCmd))
        subprocess.check_call( toolCmd )

    # OLD: to use for fleshing out other execution functions
    def execute(self, inFastas, outFile, localpair, globalpair, preservecase, reorder, 
                outputAsClustal, maxiters, gapOpeningPenalty=None, offset=None, threads=-1, verbose=True):

        inputFileName         = ""
        tempCombinedInputFile = ""

        # get the full paths of input and output files in case the user has specified relative paths
        inputFiles = []
        for f in inFastas:
            inputFiles.append(os.path.abspath(f))
        outFile = os.path.abspath(outFile)

        # ensure that all sequence IDs in each input file are unique 
        # (otherwise the alignment result makes little sense)
        # we can check before combining to localize duplications to a specific file
        for filePath in inputFiles:
            self.__seqIdsAreAllUnique(filePath)

        # if multiple fasta files are specified for input
        if len(inputFiles)>1:
            # combined specified input files into a single temp FASTA file so MAFFT can read them
            tempFileSuffix = ""
            for filePath in inputFiles:
                tempFileSuffix += "__" + os.path.basename(filePath)
            tempCombinedInputFile = util.file.mkstempfname('__combined.{}'.format(tempFileSuffix))
            with open(tempCombinedInputFile, "w") as outfile:
                for f in inputFiles:
                    with open(f, "r") as infile:
                        outfile.write(infile.read())
                #outFile.close()
            inputFileName = tempCombinedInputFile
        # if there is only once file specified, just use it
        else:
            inputFileName = inputFiles[0]

        # check that all sequence IDs in a file are unique
        self.__seqIdsAreAllUnique(inputFileName)

        # change the pwd, since the shell script that comes with mafft depends on the pwd
        # being correct
        pwdBeforeMafft = os.getcwd()
        os.chdir(os.path.dirname(self.install_and_get_path()))

        # build the MAFFT command
        toolCmd = [self.install_and_get_path()]
        toolCmd.append("--auto")
        toolCmd.append("--thread {}".format( max( int(threads), 1 )) )

        if localpair and globalpair:
            raise Exception("Alignment type must be either local or global, not both.")

        if localpair:
            toolCmd.append("--localpair")
            if not maxiters:
                maxiters = 1000
        if globalpair:
            toolCmd.append("--globalpair")
            if not maxiters:
                maxiters = 1000
        if preservecase:
            toolCmd.append("--preservecase")
        if reorder:
            toolCmd.append("--reorder")
        if gapOpeningPenalty:
            toolCmd.append("--op {penalty}".format(penalty=gapOpeningPenalty))
        if offset:
            toolCmd.append("--ep {num}".format(num=offset))
        if not verbose:
            toolCmd.append("--quiet")
        if outputAsClustal:
            toolCmd.append("--clustalout")
        if maxiters:
            toolCmd.append("--maxiterate {iters}".format(iters=maxiters))
        
        toolCmd.append(inputFileName)

        log.debug(' '.join(toolCmd))

        # run the MAFFT alignment
        with open(outFile, 'w') as outf:
            subprocess.check_call(toolCmd, stdout=outf)

        if len(tempCombinedInputFile):
            # remove temp FASTA file
            os.unlink(tempCombinedInputFile)

        # restore pwd
        os.chdir(pwdBeforeMafft)

def get_os_type():
    ''' inspects the system uname and returns a string representing the OS '''

    uname = os.uname()
    if uname[0] == "Darwin":
        return "osx"
    if uname[0] == "Linux":
        return "linux"

def get_selscan_binary_path(os_type, full=True):
    ''' returns the location of the binary relative to the extracted archive, for the given os '''

    selscanPath = "bin/"

    if os_type == "osx":
        selscanPath += "osx/"
    elif os_type == "linux":
        selscanPath += "linux/"
    elif os_type == "win":
        selscanPath += "win/"

    if full:
        selscanPath += "selscan"

        if os_type == "win":
            selscanPath += ".exe"

    return selscanPath



