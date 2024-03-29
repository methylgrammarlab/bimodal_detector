# #############################################################
#
# MIT License
#
# Copyright (c) 2022 irene unterman and ben berman
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# #############################################################

import sys
import os
import numpy as np
sys.path.append("/Users/ireneu/PycharmProjects/bimodal_detector/") ###
sys.path.append("/Users/ireneu/PycharmProjects/epiread-tools/") ###

from epiread_tools.epiparser import EpireadReader, CoordsEpiread
from epiread_tools.epiformat import epiformat_to_reader
from epiread_tools.naming_conventions import *
from epiread_tools.em_utils import calc_percent_U

from bimodal_detector.run_em import run_em, get_all_stats, do_walk_on_list
from bimodal_detector.filter_bic import *
from bimodal_detector.runner_utils import *
import logging

class Runner:

    def __init__(self, config):
        '''
        runs EM start to finish
        :param config: dict with run params
        '''
        self.config = config
        self.name = self.config["name"]
        self.reader = epiformat_to_reader[self.config["epiformat"]]
        self.outdir = self.config["outdir"] if len(self.config["outdir"]) else os.getcwd()
        if self.config["verbose"]:
            self.init_logger()
        self.results, self.stats = [], []
        self.get_pp = False
        self.n_sources = len(self.config["epiread_files"])

    def init_logger(self, level=logging.DEBUG):
        logger = logging.getLogger(self.name)
        logger.setLevel(level)
        fh = logging.FileHandler(self.config["logfile"])
        fh.setLevel(level)
        logger.addHandler(fh)
        return logger

    def __repr__(self):
        return """Name: %s, CpG location file : %s, parse SNPs: %s, walk on list: %s,
                win_size: %d, step size %d""" % (self.name, self.config["cpg_coordinates"],
            str(self.config["parse_snps"]), str(self.config["walk_on_list"]),
                                self.config["window_size"], self.config["step_size"])

    def read(self):
        reader = self.reader(self.config)
        self.interval_order, self.matrices, self.cpgs, _ = reader.get_matrices_for_intervals()
        self.sources = reader.get_sources()

    def em_all(self):
        for i, interval in enumerate(self.interval_order): #interval should never span more than 1 chromosome
            self.window_list = [(0, self.matrices[i].shape[1])]
            if self.config["walk_on_list"] is True:
                self.window_list = list(do_walk_on_list(self.window_list, self.config["window_size"], self.config["step_size"]))
            em_results = run_em(self.matrices[i], self.window_list)
            stats = get_all_stats(em_results["Indices"], em_results["Probs"], dict(zip(np.arange(len(self.sources[i])), self.sources[i])),
                                  self.n_sources, self.get_pp)
            self.results.append(em_results)
            self.stats.append(stats)

    def filter(self, bic):
        '''
        filter results by bic
        :param bic: threshold, keep only < bic
        :return:
        '''
        results, stats = [], []
        for res, stat in zip(self.results, self.stats):
            pass_filt = res["BIC"] <  bic
            filt_res = filter_em_results(res, pass_filt)
            filt_stats = []
            if filt_res["BIC"]: #anything left
                filt_stats = stat[:,pass_filt,:]
            results.append(filt_res)
            stats.append(filt_stats)
        self.results, self.stats = results, stats

    def write_sample_ids(self):
        '''
        outout Sample   ID  per sample
        :return:
        '''
        samples = ["ALL"] + self.config["epiread_files"]
        ids = np.arange(len(samples))
        with open(os.path.join(self.outdir, str(self.name) + "_sample_IDs.txt"), "w") as outfile:
            for sample, id in zip(samples, ids):
                outfile.write(sample + TAB + str(id) + "\n")

    def write_window_summary(self): #TODO: add snps
        '''
            one line per window:
        chr start end  chr start end BIC med_cpg CpG_rel_pos SNP_rel_pos SNP_alt_alleles
        chr2 100 125  chr2 110 125  -1250   4    0,20,34,88,125 56,61    A,T
        first coordinate is same as input, second is first to last cpg in the window
        :param self:
        :return:
        '''
        abs_windows = []
        input_windows = []
        rel_positions = []
        bic = []
        med_cpg = []
        for i, interval in enumerate(self.interval_order):
            if "windows" in self.results[i] and self.results[i]["windows"]: #any windows with results
                abs_windows.append(relative_intervals_to_abs(interval.chrom, self.cpgs[i], self.results[i]["windows"]))
                bic.append(np.array(self.results[i]["BIC"]))
                med_cpg.append(np.array(self.results[i]["median_cpg"]))
                input_windows.append([(interval.chrom, interval.start, interval.end)]*len(self.results[i]["windows"]))

                for x in cpg_positions_in_interval(self.cpgs[i], self.results[i]["windows"]):
                    rel_positions.append(format_array(x))
        output_array = np.hstack([np.vstack(input_windows),
                        np.vstack(abs_windows),
                        np.hstack(bic).reshape(-1,1),
                        np.hstack(med_cpg).reshape(-1, 1),
                        np.vstack(rel_positions)])
        with gzip.open(os.path.join(self.outdir, str(self.name) + "_window_summary.bedgraph.gz"), "w") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt='%s')

    def write_sample_summary(self):
        '''
        chr start end chr start end sample n_read n>0.9, n<0.1, n>0.5, pp_mean, pp_stdev, pps(optional)
        chr2 100  125 chr2 110  125  0     54      18     20      19      0.2      0.01    0.8,0.1,0.4
        :return:
        '''
        input_windows = []
        abs_windows = []
        stats = []
        for i, interval in enumerate(self.interval_order):
            if "windows" in self.results[i] and self.results[i]["windows"]: #any results
                input_windows.append([(interval.chrom, interval.start, interval.end)]*len(self.results[i]["windows"]))
                abs_windows.append(relative_intervals_to_abs(interval.chrom, self.cpgs[i], self.results[i]["windows"]))
                stats.append(self.stats[i])
        a = np.vstack(abs_windows)
        b = np.hstack(stats)
        c = np.vstack(input_windows)
        output_array = np.vstack([np.hstack([c,a, np.full(a.shape[0], x).reshape(-1,1), b[x,:,:]]) for x in range(b.shape[0])])
        with gzip.open(os.path.join(self.outdir, str(self.name) + "_sample_summary.bed.gz"), "w") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt='%s')

    def handle_empty_output(self):
        '''
        create empty files for snakemake
        :return:
        '''
        with gzip.open(os.path.join(self.outdir, str(self.name) + "_window_summary.bedgraph.gz"), "w") as outfile:
            pass
        with gzip.open(os.path.join(self.outdir, str(self.name) + "_sample_summary.bed.gz"), "w") as outfile:
            pass

    def run(self):
        self.read()
        self.em_all()
        self.filter(self.config["bic_threshold"])
        if is_empty(self.stats):
            self.handle_empty_output()
            return
        self.write_window_summary()
        self.write_sample_summary()


class ParamEstimator(Runner):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.groups = self.config["groups"]

    def write_output(self):
        '''
        The output needed to run step_1_report
        win start, win end, BIC, mean_pp_vec
        :return:
        '''
        rel_ind = 0
        rel_windows = []
        bics = []
        pp_vecs = []
        for i, interval in enumerate(self.interval_order):
            if "windows" in self.results[i] and self.results[i]["windows"]: #any results
                rel_windows.extend([(x+rel_ind, y+rel_ind) for x,y in self.results[i]["windows"]])
                bics.extend(self.results[i]["BIC"])
                rel_ind = rel_windows[-1][-1]
                pp_vecs.append(self.stats[i][:,:,-2]) #mean pp per cell type

        a = np.vstack(rel_windows)
        b = np.hstack(bics)
        c = np.hstack(pp_vecs)
        output_array = np.column_stack((a, b.reshape(-1,1), c.T))
        format_str = ['%d', '%d', '%d']+[ '%.3f']*(output_array.shape[1]-3)

        with gzip.open(os.path.join(self.outdir, str(self.name) + "_step_1.csv.gz"), "a+") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt=format_str)

    def group_sources(self):
        '''
        sources are vectors of which file each read came from
        we need to turn it to a list of groups
        These are all 1 based not to interfere with the "ALL" group
        0: ALL
        -1: empty interval
        :return:
        '''
        epiread_number_to_group = dict(enumerate(self.groups, start=1))
        self.group_set = sorted(set(self.groups)) #sorted to make sure it's the same across chunks
        group_to_group_number = {group: index for index, group in enumerate(self.group_set, start=1)}
        epiread_number_to_group[-1] = -1 #for empty
        group_to_group_number[-1] = -1 #for empty
        fun = lambda x: group_to_group_number[epiread_number_to_group[x]]
        new_sources = []
        for s in self.sources:
            new_sources.append(np.vectorize(fun)(s))
        self.sources = new_sources
        self.n_sources = len(set(self.groups))

    def run(self):
        self.read()
        self.group_sources()
        self.em_all()
        self.write_output()

class TwoStepRunner(Runner):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self):
        self.read()
        self.em_all()
        #check if empty
        #loose filter
        #check if empty
        #merge
        #rerun em
        #unmerge
        #strict filter
        #check if empty
        #write output

class AtlasEstimator(Runner):
    '''
    class to estimate lambda and theta from ref samples
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = self.config["labels"] #one for every epiread
        self.cell_types = self.config["cell_types"] #important to maintain order in output
        self.label_to_id = dict(zip(self.cell_types, np.arange(1, len(self.cell_types) + 1)))
        self.lambdas=[]

    def save_lambda(self):
        input_windows = [] #for comparisons later
        abs_windows = []
        mean_pp = []
        for i, interval in enumerate(self.interval_order):
            if "windows" in self.results[i] and self.results[i]["windows"]:  # any windows with results
                abs_windows.append(relative_intervals_to_abs(interval.chrom, self.cpgs[i], self.results[i]["windows"]))
                mean_pp.append(self.lambdas[i])
                input_windows.append([(interval.chrom, interval.start, interval.end)]*len(self.results[i]["windows"]))
        output_array = np.hstack([np.vstack(input_windows),
                                  np.vstack(abs_windows),
                                  np.hstack(mean_pp).T,
                                  ])
        header = TAB.join(self.cell_types)
        with open(os.path.join(self.outdir, str(self.name) + "_lambdas.bedgraph"), "w") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt='%s', header='chrom\tstart\tend\tchrom\tstart\tend\t'+header)

    def em_all(self):
        '''
        get stats per source instead of per sample
        only keep mean pp
        :return:
        '''
        for i, interval in enumerate(self.interval_order): #interval should never span more than 1 chromosome
            window_list = [(0, self.matrices[i].shape[1])]
            if self.config["walk_on_list"]:
                window_list = list(do_walk_on_list(window_list, self.config["window_size"], self.config["step_size"]))
            if self.matrices[i].count_nonzero() == 0: #no data
                self.results.append([])
                self.lambdas.append([])
                continue
            em_results = run_em(self.matrices[i], window_list)
            source_labels = np.array(self.labels)[self.sources[i]-1] #adjusted for index
            source_ids = [self.label_to_id[x] for x in source_labels]
            stats = get_all_stats(em_results["Indices"], em_results["Probs"], dict(zip(np.arange(len(self.sources[i])), source_ids)),
                                  len(self.cell_types), self.config["get_pp"])
            # row_filters, pp_vectors, ind_to_source, n_sources, get_pp
            self.results.append(em_results)
            self.lambdas.append(stats[1:,:,4])#remove ALL and keep only mean pp column


    def save_thetas(self):
        input_windows = []
        abs_windows = []
        theta_A = []
        theta_B = []
        for i, interval in enumerate(self.interval_order):
            if "windows" in self.results[i] and self.results[i]["windows"]:  # any windows with results
                abs_windows.append(relative_intervals_to_abs(interval.chrom, self.cpgs[i], self.results[i]["windows"]))
                input_windows.append([(interval.chrom, interval.start, interval.end)]*len(self.results[i]["windows"]))
                thetas = zip(self.results[i]["Theta_A"], self.results[i]["Theta_B"])
                for m, n in thetas:
                    theta_A.append(format_array(m))
                    theta_B.append(format_array(n))
        output_array = np.hstack([np.vstack(input_windows),
                                  np.vstack(abs_windows),
                                  np.vstack(theta_A),
                                  np.vstack(theta_B)
                                  ])
        with open(os.path.join(self.outdir, str(self.name) + "_thetas.bedgraph"), "w") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt='%s')

    def run(self):
        self.read()
        self.em_all()
        self.save_lambda()
        self.save_thetas()

class UXM_Estimator(Runner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = self.config["labels"] #one for every epiread
        self.cell_types = self.config["cell_types"] #important to maintain order in output

    def calc_u_reads(self):
        input_windows = []
        abs_windows = []
        U = []
        N = []
        for i, interval in enumerate(self.interval_order):
            window_list = [(0, self.matrices[i].shape[1])]
            if self.config["walk_on_list"]:
                window_list = list(do_walk_on_list(window_list, self.config["window_size"], self.config["step_size"]))
            abs_windows.append(relative_intervals_to_abs(interval.chrom, self.cpgs[i], window_list))
            input_windows.append([(interval.chrom, interval.start, interval.end)]*len(window_list))
            for start, end in window_list:
                mat = self.matrices[i][:,start:end].todense()
                x_c_v = (mat != NOVAL)
                # filter short reads
                len_filt = (np.sum(x_c_v, axis=1).flatten() >= self.config["min_length"])
                # count U per cell type
                source_labels = np.array(self.labels)[self.sources[i] - 1]
                percent_u = np.zeros(len(self.cell_types))
                n_fragments = np.zeros(len(self.cell_types))
                if len_filt.sum():
                    for j, cell in enumerate(self.cell_types):
                        cell_filt = np.ravel(len_filt&(source_labels==cell))
                        small = mat[cell_filt,:]
                        if not small.shape[0]: #empty region
                            continue
                        percent_u[j] = calc_percent_U(small, u_threshold=self.config["u_threshold"])
                        n_fragments[j] = small.shape[0]
                U.append(percent_u)
                N.append(n_fragments)


        output_array = np.hstack([np.vstack(input_windows),
                                  np.vstack(abs_windows),
                                  np.vstack(U),
                                  # np.vstack(N)
                                  ])
        header = TAB.join(self.cell_types)
        with open(os.path.join(self.outdir, str(self.name) + "_percent_U.bedgraph"), "w") as outfile:
            np.savetxt(outfile, output_array, delimiter=TAB, fmt='%s', header='chrom\tstart\tend\tchrom\tstart\tend\t'+header)

    def run(self):
        self.read()
        self.calc_u_reads()


#%%
