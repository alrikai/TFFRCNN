# --------------------------------------------------------
# Fast R-CNN
# Copyright (c) 2015 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Ross Girshick
# --------------------------------------------------------

import xml.dom.minidom as minidom

import os
import PIL
import numpy as np
import scipy.sparse
import subprocess
import cPickle
import math
import glob
import uuid
import scipy.io as sio
import xml.etree.ElementTree as ET

from .imdb import imdb
from .imdb import ROOT_DIR
import ds_utils
from .voc_eval import voc_eval

# TODO: make fast_rcnn irrelevant
# >>>> obsolete, because it depends on sth outside of this project
from ..fast_rcnn.config import cfg
# <<<< obsolete

import pdb

class davis(imdb):
    def __init__(self, image_set, year, devkit_path=None):
        imdb.__init__(self, 'davis_' + image_set)
        self._image_set = image_set
        self._devkit_path = self._get_default_path() if devkit_path is None \
                            else devkit_path
        self._data_path = self._devkit_path

        self._mask_ext = '.png'
        self._image_ext = '.jpg'
        self._image_index = self._load_image_set_index()
        self._remove_empty_samples()

        #TODO: need to figure out how to handle the classes. Do we want this to be
        #unique to the different segments, and if so, how we do we do the hold-out
        #data segments? They will have overlapping annotation labels as well. Is
        #this really the best way to do it?
        self._classes = ('__background__', '__object__')
        self._class_to_ind = dict(zip(self.classes, xrange(self.num_classes)))

        # Default to roidb handler
        #self._roidb_handler = self.selective_search_roidb
        self._roidb_handler = self.gt_roidb
        self._salt = str(uuid.uuid4())
        self._year = '2017'
        # DAVIS specific config options
        self.config = {}

    def image_path_at(self, i):
        """
        Return the absolute path to image i in the image sequence.
        """
        return self.image_path_from_index(self._image_index[i])

    def image_path_from_index(self, index):
        """
        Construct an image path from the image's "index" identifier
        :param index filename stem e.g. 000000
        :return filepath
        """
        image_path = os.path.join(self._data_path, 'JPEGImages',
                                  index + self._image_ext)
        assert os.path.exists(image_path), \
                'Path does not exist: {}'.format(image_path)
        return image_path

    def _load_image_set_index(self):
        """
        Load the indexes listed in this dataset's image set file.
        """
        # Example path to image set file:
        image_set_file = os.path.join(self._data_path, 'ImageSets', '2017',
                                      self._image_set + '.txt')
        assert os.path.exists(image_set_file), \
                'Path does not exist: {}'.format(image_set_file)
        with open(image_set_file) as f:
            image_dset_index = [x.strip() for x in f.readlines()]

        image_fpath = os.path.join(self._data_path, 'JPEGImages')
        image_index = []
        for image_dset in image_dset_index:
            image_fnames = glob.glob(os.path.join(image_fpath, '480p', image_dset, '*'+self._image_ext))
            #this part is rather circuitous, but it keeps the same flavor as the other dataset imdbs
            #remove the full path, cut off the leading /, cut off the image extension
            image_index.extend([img_fname.replace(image_fpath, '')[1:-4] for img_fname in image_fnames])
        return image_index

    def _remove_empty_samples(self):
        """
        Remove images with zero annotation ()
        """
        print 'Remove empty annotations: ',
        for i in range(len(self._image_index)-1, -1, -1):
            index = self._image_index[i]
            gt_filename = os.path.join(self._data_path, 'Annotations', index + self._mask_ext)

            #NOTE: not sure if it's just me, but bmx-bumps annotations for frame
            #60, 62-74 are corrupted. For now, skip them. --> seems to be fine
            #elsewhere, but are empty annotations
            #if index.split('/')[1] == 'bmx-bumps':
            #    badframes = [str(fnum).zfill(5) for fnum in range(60,75)]
            #    if index.split('/')[2] in badframes:
            #        self._image_index.pop(i)
            #        continue
            #elif index.split('/')[1] == 'scooter-board':
            #    #40-45, 66-75 are bad
            #    badframes = [str(fnum).zfill(5) for fnum in range(40,46)] + [str(fnum).zfill(5) for fnum in range(66,76)]
            #    if index.split('/')[2] in badframes:
            #        self._image_index.pop(i)
            #        continue
            #elif index.split('/')[1] == 'surf':
            #    #54 is bad
            #    badframes = ['00054']
            #    if index.split('/')[2] in badframes:
            #        self._image_index.pop(i)
            #        continue

            gt_mask = np.asarray(PIL.Image.open(gt_filename))
            mask_empty = np.sum(gt_mask) == 0
            if mask_empty == 0:
                print index,
                self._image_index.pop(i)
        print 'Done. '


    def _get_default_path(self):
        """
        Return the default path where DAVIS may be. Guess we can just symlink the
        trainval folder to be in TFFRCNN/data/DAVIS-2017
        """
        return os.path.join(cfg.DATA_DIR, 'DAVIS-2017')


    def gt_roidb(self):
        """
        Return the database of ground-truth regions of interest, aka, the annotations.

        This function loads/saves from/to a cache file to speed up future calls.
        """
        cache_file = os.path.join(self.cache_path, self.name + '_gt_roidb.pkl')
        #if os.path.exists(cache_file):
        #    with open(cache_file, 'rb') as fid:
        #        roidb = cPickle.load(fid)
        #    print '{} gt roidb loaded from {}'.format(self.name, cache_file)
        #    return roidb

        gt_roidb = [self._load_davis_annotation(index)
                    for index in self.image_index]

        with open(cache_file, 'wb') as fid:
            cPickle.dump(gt_roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote gt roidb to {}'.format(cache_file)

        return gt_roidb

    def selective_search_roidb(self):
        """
        Return the database of selective search regions of interest.
        Ground-truth ROIs are also included.

        This function loads/saves from/to a cache file to speed up future calls.
        """
        pdb.set_trace()
        cache_file = os.path.join(self.cache_path,
                                  self.name + '_selective_search_roidb.pkl')

        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} ss roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        if self._image_set != 'test':
            gt_roidb = self.gt_roidb()
            ss_roidb = self._load_selective_search_roidb(gt_roidb)
            roidb = imdb.merge_roidbs(gt_roidb, ss_roidb)
        else:
            roidb = self._load_selective_search_roidb(None)
        with open(cache_file, 'wb') as fid:
            cPickle.dump(roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote ss roidb to {}'.format(cache_file)

        return roidb

    def rpn_roidb(self):
        pdb.set_trace()
        if self._image_set != 'test':
            gt_roidb = self.gt_roidb()
            rpn_roidb = self._load_rpn_roidb(gt_roidb)
            roidb = imdb.merge_roidbs(gt_roidb, rpn_roidb)
        else:
            roidb = self._load_rpn_roidb(None)

        return roidb

    def _load_rpn_roidb(self, gt_roidb):
        filename = self.config['rpn_file']
        print 'loading {}'.format(filename)
        assert os.path.exists(filename), \
               'rpn data not found at: {}'.format(filename)
        with open(filename, 'rb') as f:
            box_list = cPickle.load(f)
        return self.create_roidb_from_box_list(box_list, gt_roidb)

    def _load_selective_search_roidb(self, gt_roidb):
        filename = os.path.abspath(os.path.join(self._data_path,
                                                'selective_search_data',
                                                self.name + '.mat'))
        assert os.path.exists(filename), \
               'Selective search data not found at: {}'.format(filename)
        raw_data = sio.loadmat(filename)['boxes'].ravel()

        box_list = []
        for i in xrange(raw_data.shape[0]):
            boxes = raw_data[i][:, (1, 0, 3, 2)] - 1
            keep = ds_utils.unique_boxes(boxes)
            boxes = boxes[keep, :]
            keep = ds_utils.filter_small_boxes(boxes, self.config['min_size'])
            boxes = boxes[keep, :]
            box_list.append(boxes)

        return self.create_roidb_from_box_list(box_list, gt_roidb)

    def _load_davis_annotation(self, index):
        gt_filename = os.path.join(self._data_path, 'Annotations', index + self._mask_ext)
        gt_mask = np.asarray(PIL.Image.open(gt_filename))
        image_labels = np.sort(np.unique(gt_mask))

        #dont take the background
        num_objs = len(image_labels[1:])
        boxes = np.zeros((num_objs, 4), dtype=np.int32)
        gt_classes = np.zeros((num_objs), dtype=np.int32)
        # just the same as gt_classes
        overlaps = np.zeros((num_objs, self.num_classes), dtype=np.float32)
        # "Seg" area for pascal is just the box area
        seg_areas = np.zeros((num_objs), dtype=np.float32)

        for idx, label in enumerate(image_labels[1:]):
            obj_idxs = np.where(gt_mask == label)
            r_min = float(np.min(obj_idxs[0]))
            r_max = float(np.max(obj_idxs[0]))
            c_min = float(np.min(obj_idxs[1]))
            c_max = float(np.max(obj_idxs[1]))

            #assumes we are doing binary classification
            cls = self._class_to_ind['__object__']
            #TODO: figure out if the convention is (r, c, r, c) or {c, r, c, r)
            boxes[idx, :] = [c_min, r_min, c_max, r_max]
            gt_classes[idx] = cls
            overlaps[idx, cls] = 1.0
            seg_areas[idx] = (c_max - c_min + 1) * (r_max - r_min + 1)

        overlaps = scipy.sparse.csr_matrix(overlaps)
        return {'boxes' : boxes,
                'gt_classes': gt_classes,
                'gt_overlaps' : overlaps,
                'flipped' : False,
                'seg_areas' : seg_areas}

#-------------------------------------------------------------------------------

    #since this is just going to be a step in the pipeline, just output the bounding boxes for now
    def _write_davis_results_file(self, all_boxes):
        for cls_ind, cls in enumerate(self.classes):
            if cls == '__background__':
                continue
            print 'Writing {} VOC results file'.format(cls)
            filename = self._get_voc_results_file_template().format(cls)
            with open(filename, 'wt') as f:
                for im_ind, index in enumerate(self.image_index):
                    dets = all_boxes[cls_ind][im_ind]
                    if dets == []:
                        continue
                    # the VOCdevkit expects 1-based indices
                    for k in xrange(dets.shape[0]):
                        f.write('{:s} {:.3f} {:.1f} {:.1f} {:.1f} {:.1f}\n'.
                            format(index, dets[k, -1],              # filename(stem), score
                                   dets[k, 0] + 1, dets[k, 1] + 1,  # x1, y1, x2, y2
                                   dets[k, 2] + 1, dets[k, 3] + 1))

    def _do_python_eval(self, output_dir = 'output'):
        annopath = os.path.join(
            self._devkit_path,
            'Annotations', '{:s}.xml')
        imagesetfile = os.path.join(
            self._devkit_path,
            'ImageSets', 'Main',
            self._image_set + '.txt')
        cachedir = os.path.join(self._devkit_path, 'annotations_cache')
        aps = []
        # The PASCAL VOC metric changed in 2010
        use_07_metric = False
        print 'VOC07 metric? ' + ('Yes' if use_07_metric else 'No')
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        for i, cls in enumerate(self._classes):
            if cls == '__background__':
                continue
            filename = self._get_voc_results_file_template().format(cls)
            rec, prec, ap = voc_eval(filename, annopath, imagesetfile, cls, cachedir,
                                     ovthresh=0.5, use_07_metric = use_07_metric)
            aps += [ap]
            print('AP for {} = {:.4f}'.format(cls, ap))
            with open(os.path.join(output_dir, cls + '_pr.pkl'), 'w') as f:
                cPickle.dump({'rec': rec, 'prec': prec, 'ap': ap}, f)
        print('Mean AP = {:.4f}'.format(np.mean(aps)))
        print('~~~~~~~~')
        print('Results:')
        for ap in aps:
            print('{:.3f}'.format(ap))
        print('{:.3f}'.format(np.mean(aps)))
        print('~~~~~~~~')
        print('')
        print('--------------------------------------------------------------')
        print('Results computed with the **unofficial** Python eval code.')
        print('Results should be very close to the official MATLAB eval code.')
        print('Recompute with `./tools/reval.py --matlab ...` for your paper.')
        print('-- Thanks, The Management')
        print('--------------------------------------------------------------')

    def _do_matlab_eval(self, output_dir='output'):
        print '-----------------------------------------------------'
        print 'Computing results with the official MATLAB eval code.'
        print '-----------------------------------------------------'
        path = os.path.join(cfg.ROOT_DIR, 'lib', 'datasets',
                            'VOCdevkit-matlab-wrapper')
        cmd = 'cd {} && '.format(path)
        cmd += '{:s} -nodisplay -nodesktop '.format(cfg.MATLAB)
        cmd += '-r "dbstop if error; '
        cmd += 'voc_eval(\'{:s}\',\'{:s}\',\'{:s}\',\'{:s}\'); quit;"' \
               .format(self._devkit_path, self._get_comp_id(),
                       self._image_set, output_dir)
        print('Running:\n{}'.format(cmd))
        status = subprocess.call(cmd, shell=True)


    def evaluate_detections(self, all_boxes, output_dir):
        self._write_davis_results_file(all_boxes)
        self._do_python_eval(output_dir)
        if self.config['matlab_eval']:
            self._do_matlab_eval(output_dir)
        if self.config['cleanup']:
            for cls in self._classes:
                if cls == '__background__':
                    continue
                filename = self._get_voc_results_file_template().format(cls)
                os.remove(filename)

    def competition_mode(self, on):
        if on:
            self.config['use_salt'] = False
            self.config['cleanup'] = False
        else:
            self.config['use_salt'] = True
            self.config['cleanup'] = True
