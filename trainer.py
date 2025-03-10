import numpy as np
import matplotlib.pyplot as plt
import math
import os
import torch
import pickle
from argparse import ArgumentParser
from copy import deepcopy

from torch import optim
import models
import utils as ut
import datasets as dt
import data_utils as dtul
import grid_predictor as grid
from paths import get_paths
import losses as lo

from dataloader import *
from trainer_helper import *
from eval_helper import *
from sampler import *

import pandas as pd

torch.manual_seed(42)
torch.cuda.manual_seed_all(42)

def make_args_parser():
    parser = ArgumentParser()
    parser.add_argument(
        "--ssi_run_time",
        type=int,
        default="1",
        help="""ssi run time""",
    )
    parser.add_argument(
        "--ssi_loop",
        type=int,
        default="1",
        help="""ssi run time""",
    )
    parser.add_argument(
        "--save_results",
        type=str,
        default="F",
        help="""whether you need to save the lon, lat, rr, acc1, acc3 into a csv file for the final evaluation""",
    )
    parser.add_argument(
        "--unsuper_dataset",
        type=str,
        default="inat_2017",
        help="""this is the dataset used for unsupervised learning training,
                e.g., inat_2018, inat_2017, birdsnap, nabirds, yfcc, fmow""",
    )
    parser.add_argument(
        "--unsuper_meta_type",
        type=str,
        default="birdsnap",
        help="""this is the meta_type used for unsupervised learning training,
            e.g., orig_meta, ebird_meta""",
    )  # orig_meta, ebird_meta

    parser.add_argument(
        "--dataset",
        type=str,
        default="nabirds",  # ,"",birdsnap
        choices=[
            "inat_2021",
            "inat_2018",
            "inat_2017",
            "birdsnap",
            "nabirds",
            "yfcc",
            "fmow",
            "sustainbench_asset_index",
            "sustainbench_under5_mort",
            "sustainbench_water_index",
            "sustainbench_women_bmi",
            "sustainbench_women_edu",
            "sustainbench_sanitation_index",
            "mosaiks_population",
            "mosaiks_elevation",
            "mosaiks_forest_cover",
            "mosaiks_nightlights",
        ],
        help="""Dataset to use. Options are: inat_2021, inat_2018, inat_2017, birdsnap, nabirds, yfcc, fmow, sustainbench_asset_index, sustainbench_under5_mort, sustainbench_water_index, sustainbench_women_bmi, sustainbench_women_edu, sustainbench_sanitation_index,mosaiks_population, mosaiks_elevation, mosaiks_forest_cover, mosaiks_nightlights""",
    )

    parser.add_argument(
        "--meta_type",
        type=str,
        default="ebird_meta",
        help="""e.g., orig_meta, ebird_meta""",
    )  # orig_meta, ebird_meta
    parser.add_argument("--eval_split", type=str, default="val", help="""val, test""")
    parser.add_argument(
        "--load_val_op",
        type=str,
        default="T",
        help="""whether to pre-load the dataset with invalid dataset for final evaluation""",
    )
    parser.add_argument(
        "--cnn_model", type=str, default="inception_v3", help="""cnn model type"""
    )
    parser.add_argument(
        "--load_cnn_predictions",
        type=str,
        default="T",
        help="""whether to load CNN prediction on train/val/test dataset""",
    )
    parser.add_argument(
        "--load_cnn_features",
        type=str,
        default="T",
        help="""whether to load CNN feature (2048 dimention) on val/test dataset""",
    )
    parser.add_argument(
        "--load_cnn_features_train",
        type=str,
        default="T",
        help="""whether to load CNN feature (2048 dimention) on training dataset""",
    )
    parser.add_argument(
        "--load_img",
        type=str,
        default="F",
        help="""whether to load images for train/val/test dataset""",
    )

    parser.add_argument(
        "--inat2018_resolution",
        type=str,
        default="standard",
        help="""e.g.,
        high_res; high resolution fine tuned features
        standard: standard fine tuned features
        pretrain: pretrained inception_v3 feature
    """,
    )
    parser.add_argument(
        "--cnn_pred_type",
        type=str,
        default="full",
        help="""the type of CNN prediction we want to obtain e.g.,
        full: default, predictions from the fully train CNN model
        fewshot: prediction from the CNN model in few-shot settings
    """,
    )
    parser.add_argument(
        "--sustainbench_num_rbf_anchor_pts",
        type=int,
        default=100,
        help="""The number of RBF anchor points used in in the rbf nl_mean feature encoder for the sustain bench dataset
    """,
    )

    parser.add_argument(
        "--sustainbench_rbf_kernel_size",
        type=int,
        default=50,
        help="""The number of RBF kernel_size used in in the rbf nl_mean feature encoder for the sustain bench dataset
    """,
    )
    parser.add_argument(
        "--sustainbench_net_dropout",
        type=float,
        default=0.25,
        help="Dropout rate for the sustainbench network",
    )

    parser.add_argument(
        "--sustainbench_hidden_dim",
        type=int,
        default=128,
        help="The number of hidden dimensions for the sustainbench network",
    )

    parser.add_argument(
        "--mosaiks_net_dropout",
        type=float,
        default=0.1,
        help="Dropout rate for the mosaiks network",
    )

    parser.add_argument(
        "--mosaiks_hidden_dim",
        type=int,
        default=128,
        help="The number of hidden dimensions for the mosaiks network",
    )

    parser.add_argument("--device", type=str, default="cuda:0")

    parser.add_argument("--model_dir", type=str, default="../models/ssi/")
    parser.add_argument("--num_epochs", type=int, default=28)

    parser.add_argument(
        "--embed_dim_before_regress",
        type=int,
        default=64,
        help="embedding dim before regress",
    )  # for regression, the loc encoder returns a params["embed_dim_before_regress"]-dim location embed and a params["embed_dim_before_regress"]-dim image embed

    parser.add_argument(
        "--num_epochs_unsuper",
        type=int,
        default=30,
        help="""number of epoch for unsupervised training""",
    )

    # space encoder
    parser.add_argument(
        "--spa_enc_type",
        type=str,
        default="xyz",
        help="""this is the type of location encoder, e.g., Space2Vec-grid, Space2Vec-theory, xyz, NeRF,Sphere2Vec-sphereC, Sphere2Vec-sphereC+, Sphere2Vec-sphereM, Sphere2Vec-sphereM+, Sphere2Vec-dfs, rbf, rff, wrap, wrap_ffn, tile_ffn""",
    )
    parser.add_argument(
        "--frequency_num",
        type=int,
        default=32,
        help="The number of frequency used in the space encoder",
    )
    parser.add_argument(
        "--max_radius",
        type=float,
        default=1.0,
        help="The maximum frequency in the space encoder",
    )
    parser.add_argument(
        "--min_radius",
        type=float,
        default=0.000001,
        help="The minimum frequency in the space encoder",
    )
    parser.add_argument(
        "--num_hidden_layer",
        type=int,
        default=1,
        help="The number of hidden layer in the space encoder",
    )
    parser.add_argument(
        "--hidden_dim",
        type=int,
        default=512,
        help="The hidden dimention in feedforward NN in the (global) space encoder",
    )

    parser.add_argument(
        "--num_rbf_anchor_pts",
        type=int,
        default=200,
        help="The number of RBF anchor points used in in the space encoder",
    )
    parser.add_argument(
        "--rbf_kernel_size",
        type=float,
        default=1.0,
        help='The RBF kernel size in the "rbf" space encoder',
    )

    # spa enc (not change)
    parser.add_argument(
        "--loc_encode",
        type=str,
        default="encode_cos_sin",
        help="""e.g., encode_cos_sin, encode_3D, encode_none""",
    )
    parser.add_argument(
        "--num_filts", type=int, default=256, help="spatial embedding dimension"
    )
    parser.add_argument(
        "--freq_init",
        type=str,
        default="geometric",
        help="the frequency initialization method",
    )
    parser.add_argument(
        "--spa_f_act",
        type=str,
        default="leakyrelu",
        help="the activation function used by Space encoder",
    )
    parser.add_argument(
        "--map_range",
        nargs="+",
        type=float,
        default=[-162, -59, 20, 56],  # [-180, 180, -90, 90],
        help="the maximum map extent, (xmin, xmax, ymin, ymax)",
    )
    parser.add_argument(
        "--use_layn",
        type=str,
        default="T",
        help="use layer normalization or not in feedforward NN in the (global) space encoder",
    )
    parser.add_argument(
        "--skip_connection",
        type=str,
        default="T",
        help="skip connection or not in feedforward NN in the (global) space encoder",
    )
    parser.add_argument(
        "--spa_enc_use_postmat",
        type=str,
        default="T",
        help="whether to use post matrix in spa_enc",
    )
    parser.add_argument(
        "--use_date_feats",
        type=str,
        default="F",
        help="if False date feature is not used",
    )
    parser.add_argument(
        "--date_encode",
        type=str,
        default="encode_cos_sin",
        help="""e.g., encode_cos_sin, encode_none""",
    )

    # loss
    parser.add_argument(
        "--train_loss",
        type=str,
        default="full_loss",
        help="""appending '_user' models the user location and object affinity - see losses.py,
            e.g.full_loss_user, full_loss""",
    )
    parser.add_argument(
        "--neg_rand_type",
        type=str,
        default="spherical",
        help="""location negative sampling method,
    e.g., spherical: uniformed sampled on surface of sphere
          sphereicalold: old sphereical methoid
    """,
    )
    parser.add_argument(
        "--train_sample_ratio",
        type=float,
        default=0.01,  # 1.0,
        help="""The training dataset sample ratio for supervised learning""",
    )
    parser.add_argument(
        "--train_sample_method",
        type=str,
        default="random-fix",
        help="""The training dataset sample method
        1.1 stratified: stratified sampling, # samples in each class is propotional to the training distribution, each class at less has one sample
        1.2 random: random sampling, just random sample regardless the class distribution
        2.1 fix: sample first time and fix the sample indices
        2.2 random: random sample every times
        3. ssi-sample: sample based on the spatial self information

        stratified-fix: defaultå
        stratified-random:
        random-fix:
        random-random:
        ssi-sample
    """,
    )
    parser.add_argument(
        "--ssi_sample_feat_type",
        type=str,
        default="feat",
        help="""The feature type used in spatial self information sampling, e.g., feat, pred""",
    )

    parser.add_argument(
        "--ssi_sample_k",
        type=int,
        default=20,
        help="""ssi_sample_k""",
    )

    parser.add_argument(
        "--ssi_sample_radius",
        type=float,
        default=100,
        help="""ssi_sample_radius""",
    )

    parser.add_argument(
        "--ssi_sample_n_bg",
        type=int,
        default=100,
        help="""ssi_sample_n_bg""",
    )

    parser.add_argument(
        "--ssi_sample_bucket_size",
        type=float,
        default=0.1,
        help="""ssi_sample_bucket_size""",
    )

    # unsupervise loss
    parser.add_argument(
        "--unsuper_loss",
        type=str,
        default="none",
        help="""unsupervised training loss, e.g.,
            none: no unsupervised training
            l2regress: from location embedding, directly regress image feature
            imgcontloss: image feature project to loc_emb_dim, do NLL loss
            imgcontlossnolocneg: image feature project to loc_emb_dim, do NLL loss
            imgcontlosssimcse: NLL loss, in batch location-image loss + location negative sampling + SimCSE
            contsoftmax: InfoNCE, (one loc to all image), in batch location-image loss + negative location sampling + SimCSE
            contsoftmaxsym: InfoNCE, symmetric cross entropy, in batch location-image loss + negative location sampling + SimCSE
        """,
    )
    parser.add_argument(
        "--num_neg_rand_loc",
        type=int,
        default=1,
        help="number of negative random location used for contrastive loss",
    )
    parser.add_argument(
        "--rand_sample_weight",
        type=float,
        default=1.0,
        help="The weight of rand sample loss",
    )
    parser.add_argument(
        "--simcse_weight",
        type=float,
        default=0.0,
        help="The weight of rand sample loss",
    )
    parser.add_argument(
        "--unsuper_lr",
        type=float,
        default=0.001,
        help="learning rate for unsupervised learning training",
    )
    parser.add_argument(
        "--do_unsuper_train",
        type=str,
        default="F",
        help="whether or not to do unsupervised training",
    )
    parser.add_argument(
        "--load_unsuper_model",
        type=str,
        default="F",
        help="whether or not to load the pretrained unsupervised learning model if it exists",
    )
    parser.add_argument(
        "--unsuper_temp_inbatch",
        type=float,
        default=1,
        help="""when unsuper_loss == contsoftmax,
            this is the temperature used for the 1st in batch location-image loss""",
    )
    parser.add_argument(
        "--unsuper_temp_negloc",
        type=float,
        default=1,
        help="""when unsuper_loss == contsoftmax,
            this is the temperature used for the 2nd negative location sampling loss""",
    )
    parser.add_argument(
        "--unsuper_temp_simcse",
        type=float,
        default=1,
        help="""when unsuper_loss == contsoftmax,
            this is the temperature used for the 3rd SimCSE loss""",
    )

    parser.add_argument(
        "--unsuper_eval_frequency",
        type=int,
        default=10,
        help="The frequency to Eval the location encoder unsupervised",
    )

    # training
    parser.add_argument("--lr", type=float, default=0.001, help="learning rate")
    parser.add_argument(
        "--lr_decay", type=float, default=0.98, help="learning rate decay"
    )
    parser.add_argument("--weight_decay", type=float, default=0.0, help="weight decay")
    parser.add_argument(
        "--dropout",
        type=float,
        default=0.5,
        help="The dropout rate used in feedforward NN in the (global) space encoder",
    )
    parser.add_argument("--batch_size", type=int, default=1024, help="batch size")
    parser.add_argument("--log_frequency", type=int, default=50, help="batch size")
    parser.add_argument(
        "--max_num_exs_per_class", type=int, default=100, help="batch size"
    )
    parser.add_argument(
        "--balanced_train_loader", type=str, default="T", help="banlance train loader"
    )
    parser.add_argument(
        "--eval_frequency",
        type=int,
        default=4,
        help="The frequency to Eval the location encoder model classification accuracy",
    )
    parser.add_argument(
        "--unsuper_save_frequency",
        type=int,
        default=5,
        help="The frequency to save the unsuper model",
    )

    parser.add_argument(
        "--load_super_model",
        type=str,
        default="F",
        help="whether or not to load pretrained supervised training model",
    )
    parser.add_argument(
        "--do_super_train",
        type=str,
        default="T",
        help="whether or not to do supervised training",
    )

    parser.add_argument(
        "--do_epoch_save",
        type=str,
        default="F",
        help="Whether we want to save model at different epoch",
    )

    return parser


def update_params(params):
    if params["dataset"] not in ["birdsnap", "nabirds"]:
        params["meta_type"] = ""  # orig_meta, ebird_meta
    params["regress_dataset"] = [
        "sustainbench_asset_index",
        "sustainbench_under5_mort",
        "sustainbench_water_index",
        "sustainbench_women_bmi",
        "sustainbench_women_edu",
        "sustainbench_sanitation_index",
        "mosaiks_population",
        "mosaiks_elevation",
        "mosaiks_forest_cover",
        "mosaiks_nightlights",
    ]
    if params["dataset"] in params["regress_dataset"]:
        params["use_date_feats"] = "F"
        params["eval_split"] = "test"
        params["load_cnn_features_train"] = "T"
        params["load_cnn_features"] = "T"
        params["load_cnn_predictions"] = "F"
    # elif params["dataset"] in [
    #     "sustainbench_asset_index",
    #     "sustainbench_under5_mort",
    #     "sustainbench_water_index",
    # ]:
    #     params["split"] = "test"
    #     params["load_cnn_features_train"] = "F"
    #     params["load_cnn_features"] = "F"

    for var in [
        "save_results",
        "load_val_op",
        "use_layn",
        "skip_connection",
        "spa_enc_use_postmat",
        "balanced_train_loader",
        "use_date_feats",
        "load_cnn_predictions",
        "load_cnn_features",
        "load_cnn_features_train",
        "do_unsuper_train",
        "load_unsuper_model",
        "do_super_train",
        "load_super_model",
        "load_img",
        "do_epoch_save",
    ]:
        if params[var] == "T":
            params[var] = True
        elif params[var] == "F":
            params[var] = False
        else:
            raise Exception(f"Unknown {var}={params[var]}")

    return params


class Trainer:
    """
    Trainer
    """

    def __init__(self, args, console=True):
        self.args = args
        params = vars(args)

        params = update_params(params)

        self.make_spa_enc_type_list()

        self.op = self.load_dataset_(params)

        if params["dataset"] not in params["regress_dataset"]:
            params["num_classes"] = self.op["num_classes"]
            self.load_val_dataset(params)

        params = self.sample_rbf_anchor_pts(params)

        self.make_model_file(params)

        self.logger = self.make_logger(params)

        if params["dataset"] not in params["regress_dataset"]:
            self.make_image_dir(params)
            self.process_users(params)

        self.log_dataset_status(params, logger=self.logger)

        self.load_ocean_mask()

        self.create_train_val_data_loader(params)

        self.create_train_sample_data_loader(params)

        self.params = params

        self.loc_enc_model = self.create_loc_model()

        self.regress_enc_model = self.create_regress_model()

        if (
            self.params["spa_enc_type"] not in self.spa_enc_baseline_list
            and self.params["dataset"] not in params["regress_dataset"]
        ):
            self.optimizer = torch.optim.Adam(
                self.loc_enc_model.parameters(),
                lr=params["lr"],
                weight_decay=params["weight_decay"],
            )
        elif self.params["dataset"] in params["regress_dataset"]:
            self.optimizer = torch.optim.Adam(
                self.regress_enc_model.parameters(),
                lr=params["lr"],
                weight_decay=params["weight_decay"],
            )

        self.set_up_grid_predictor()

        self.epoch = 0

    def make_spa_enc_type_list(self):
        self.spa_enc_baseline_list = ut.get_spa_enc_baseline_list()

    def load_dataset_(self, params):
        # print('Dataset   \t' + params['dataset'])
        # op = dt.load_dataset(params, 'val', True, True)
        op = dt.load_dataset(
            params,
            eval_split=params["eval_split"],
            train_remove_invalid=True,
            eval_remove_invalid=True,
            load_cnn_predictions=params["load_cnn_predictions"],
            load_cnn_features=params["load_cnn_features"],
            load_cnn_features_train=params["load_cnn_features_train"],
        )

        if params["dataset"] not in params["regress_dataset"]:
            if not params["load_cnn_features_train"]:
                op["train_feats"] = None

            if not params["load_cnn_features"]:
                op["val_feats"] = None

            if not params["load_cnn_predictions"]:
                op["val_preds"] = None

        return op

    def load_val_dataset(self, params, spa_enc_type_list=["no_prior"]):
        """
        We need to load the dataset with invalid samples for final evaluation
        """
        if params["load_val_op"]:
            spa_enc_type_list = self.check_spa_enc_type_list(params, spa_enc_type_list)
            print("Pre-load dataset for final evaluation")
            # load data and features
            if "tang_et_al" in spa_enc_type_list:
                op = dt.load_dataset(
                    params,
                    eval_split=params["eval_split"],
                    train_remove_invalid=True,
                    eval_remove_invalid=False,  # do not remove invalid in val/test
                    load_cnn_predictions=True,
                    load_cnn_features=True,
                    load_cnn_features_train=False,
                )
            # classification
            elif params["dataset"] in params["regress_dataset"]:
                op = dt.load_dataset(
                    params,
                    eval_split=params["eval_split"],
                    train_remove_invalid=True,
                    eval_remove_invalid=False,  # do not remove invalid in val/test
                    load_cnn_predictions=True,
                    load_cnn_features=False,
                    load_cnn_features_train=False,
                )
            # regression
            else:
                op = dt.load_dataset(
                    params,
                    eval_split=params["eval_split"],
                    train_remove_invalid=True,
                    eval_remove_invalid=False,  # do not remove invalid in val/test
                    load_cnn_predictions=True,
                    load_cnn_features=True,
                    load_cnn_features_train=True,
                )

            val_op = {}
            for key in op:
                if key.startswith("val"):
                    val_op[key] = op[key]
            del op
            self.val_op = val_op
        else:
            self.val_op = None

    def sample_rbf_anchor_pts(self, params):
        # params['rbf_anchor_pt_ids']: the samples indices in train_locs whose correponding points are unsed as rbf anbchor points
        if params["spa_enc_type"] == "rbf":
            params["rbf_anchor_pt_ids"] = list(
                np.random.choice(
                    np.arange(len(self.op["train_locs"])),
                    params["num_rbf_anchor_pts"],
                    replace=False,
                )
            )

        else:
            params["rbf_anchor_pt_ids"] = None
        return params

    def make_model_file(self, params):
        # get unsuper_model_path
        param_args = ut.make_model_file_param_args(
            params, spa_enc_type=params["spa_enc_type"], get_unsuper_model_path=True
        )

        if param_args is None:
            params["unsuper_model_file_name"] = None
        else:
            if params["meta_type"] == "":
                params["unsuper_model_file_name"] = params[
                    "model_dir"
                ] + "model_{}_{}_{}.pth.tar".format(
                    params["dataset"], params["spa_enc_type"], param_args
                )
            else:
                params["unsuper_model_file_name"] = params[
                    "model_dir"
                ] + "model_{}_{}_{}_{}.pth.tar".format(
                    params["dataset"],
                    params["meta_type"],
                    params["spa_enc_type"],
                    param_args,
                )

        # get supervised  model_path
        param_args = ut.make_model_file_param_args(
            params, spa_enc_type=params["spa_enc_type"], get_unsuper_model_path=False
        )
        if param_args is None:
            params["model_file_name"] = None
        else:
            if params["meta_type"] == "":
                params["model_file_name"] = params[
                    "model_dir"
                ] + "model_{}_{}_{}_{}.pth.tar".format(
                    params["dataset"],
                    params["train_sample_ratio"],
                    params["spa_enc_type"],
                    param_args,
                )
            else:
                params["model_file_name"] = params[
                    "model_dir"
                ] + "model_{}_{}_{}_{}_{}.pth.tar".format(
                    params["dataset"],
                    params["meta_type"],
                    params["train_sample_ratio"],
                    params["spa_enc_type"],
                    param_args,
                )

        return

    def make_image_dir(self, params):
        op_dir = "image/ims_{}_{}/".format(params["dataset"], params["spa_enc_type"])
        if not os.path.isdir(op_dir):
            os.makedirs(op_dir)
        params["op_dir"] = op_dir
        return

    def make_logger(self, params):
        # make logger file
        params["log_file_name"] = params["model_file_name"].replace(".pth.tar", ".log")
        logger = ut.setup_logging(params["log_file_name"], console=True, filemode="a")
        # params['logger'] = logger
        return logger

    def process_users(self, params):
        # process users
        # NOTE we are only modelling the users in the train set - not the val
        # un_users: a sorted list of unique user id
        # train_users: the indices in un_users which indicate the original train user id
        self.un_users, self.train_users_np = np.unique(
            self.op["train_users"], return_inverse=True
        )
        # train_users: torch.tensor, shape (num_train), training user ids
        # self.train_users = torch.from_numpy(self.train_users).to(params['device'])

        # val_users: torch.tensor, shape (num_val), val user ids
        # self.val_users = torch.from_numpy(self.val_users).to(params['device'])

        params["num_users"] = len(self.un_users)
        if "user" in params["train_loss"]:
            # need to have more than one user
            assert params["num_users"] != 1
        return

    def log_dataset_status(self, params, logger):
        # print stats
        if params["dataset"] not in params["regress_dataset"]:
            logger.info("\nnum_classes\t{}".format(params["num_classes"]))
            logger.info("num train    \t{}".format(len(self.op["train_locs"])))
            logger.info("num val      \t{}".format(len(self.op["val_locs"])))
            logger.info("train loss   \t" + params["train_loss"])
            logger.info("model name   \t" + params["model_file_name"])
            logger.info("num users    \t{}".format(params["num_users"]))
            if params["meta_type"] != "":
                logger.info("meta data    \t" + params["meta_type"])
        else:
            logger.info("num train    \t{}".format(len(self.op["train_locs"])))
            logger.info("num val      \t{}".format(len(self.op["val_locs"])))
            logger.info("train loss   \t" + params["train_loss"])
            logger.info("model name   \t" + params["model_file_name"])

    def load_ocean_mask(self):
        # load ocean mask for plotting
        self.mask = np.load(get_paths("mask_dir") + "ocean_mask.npy").astype(int)

    def create_dataset_data_loader(
        self,
        params,
        data_flag,
        labels=None,
        classes=None,
        locs=None,
        dates=None,
        users=None,
        cnn_features=None,
    ):
        """
        Args:
            params:
            data_flag: train/val/test
            labels: for regression, np.array(), shape (num_samples, ), image labels
            classes: for classfication, np.array(), shape (num_samples, ), image class labels
            locs: np.array(), shape (num_samples, 2), image locations
            dates: np.array(), shape (num_samples, ), image dates
            users: np.array(), shape (num_samples, ), user ids,
            cnn_features: np.array(), shape (num_samples, 2048)
        """
        # Classification
        if params["dataset"] not in params["regress_dataset"]:
            # data loaders
            # labels: torch.tensor, shape [num_samples, ]
            labels = torch.from_numpy(classes)  # .to(params['device'])
            # loc_feats: torch.tensor, shape [num_samples, 2] or [num_samples, 3]
            # qc: Generate random locations
            num_samples = labels.shape[0]  
            random_locs = np.column_stack([
                np.random.uniform(-180, 180, num_samples),  
                np.random.uniform(-90, 90, num_samples)     
            ])
            loc_feats = ut.generate_model_input_feats(
                spa_enc_type=params["spa_enc_type"],
                #locs=locs,
                locs=random_locs,
                dates=dates,
                params=params,
                device=params["device"],
            ).cpu()

            users_tensor = torch.from_numpy(users)  # .to(params['device'])

            if cnn_features is not None:
                cnn_feats = torch.from_numpy(cnn_features)  # .to(params['device'])
            else:
                cnn_feats = None

            if data_flag == "train":
                # training dataset
                dataset = LocationDataLoader(
                    loc_feats=loc_feats,
                    labels=labels,
                    users=users_tensor,
                    num_classes=params["num_classes"],
                    is_train=True,
                    cnn_features=cnn_feats,
                    device=params["device"],
                )
                if params["balanced_train_loader"]:
                    data_loader = torch.utils.data.DataLoader(
                        dataset,
                        num_workers=0,
                        batch_size=params["batch_size"],
                        sampler=ut.BalancedSampler(
                            classes.tolist(),
                            params["max_num_exs_per_class"],
                            use_replace=False,
                            multi_label=False,
                        ),
                        shuffle=False,
                    )
                else:
                    data_loader = torch.utils.data.DataLoader(
                        dataset,
                        num_workers=0,
                        batch_size=params["batch_size"],
                        shuffle=True,
                    )
            else:
                dataset = LocationDataLoader(
                    loc_feats=loc_feats,
                    labels=labels,
                    users=users_tensor,
                    num_classes=params["num_classes"],
                    is_train=False,
                    cnn_features=cnn_feats,
                    device=params["device"],
                )
                data_loader = torch.utils.data.DataLoader(
                    dataset,
                    num_workers=0,
                    batch_size=params["batch_size"],
                    shuffle=False,
                )

            return dataset, data_loader, labels, loc_feats, users_tensor, cnn_feats

        # Regression
        else:
            # data loaders
            # labels: torch.tensor, shape [num_samples, ]
            labels = torch.from_numpy(labels)  # .to(params['device'])
            # loc_feats: torch.tensor, shape [num_samples, 2] or [num_samples, 3]
            loc_feats = ut.generate_model_input_feats(
                spa_enc_type=params["spa_enc_type"],
                locs=locs,
                dates=dates,
                params=params,
                device=params["device"],
            ).cpu()

            if cnn_features is not None:
                cnn_feats = torch.from_numpy(cnn_features)  # .to(params['device'])
            else:
                cnn_feats = None

            if data_flag == "train":
                # training dataset
                dataset = LocationDataLoader(
                    loc_feats=loc_feats,
                    labels=labels,
                    is_train=True,
                    users=None,
                    cnn_features=cnn_feats,
                    device=params["device"],
                )
                if params["balanced_train_loader"]:
                    data_loader = torch.utils.data.DataLoader(
                        dataset,
                        num_workers=0,
                        batch_size=params["batch_size"],
                        sampler=ut.BalancedSampler(
                            classes.tolist(),
                            params["max_num_exs_per_class"],
                            use_replace=False,
                            multi_label=False,
                        ),
                        shuffle=False,
                    )
                else:
                    data_loader = torch.utils.data.DataLoader(
                        dataset,
                        num_workers=0,
                        batch_size=params["batch_size"],
                        shuffle=True,
                    )
            else:
                dataset = LocationDataLoader(
                    loc_feats=loc_feats,
                    labels=labels,
                    users=None,
                    is_train=False,
                    cnn_features=cnn_feats,
                    device=params["device"],
                )
                data_loader = torch.utils.data.DataLoader(
                    dataset,
                    num_workers=0,
                    batch_size=params["batch_size"],
                    shuffle=False,
                )

            return dataset, data_loader, labels, loc_feats, cnn_feats

    def get_next_available_filename(self, base_filename):
        run_number = 1
        while os.path.exists(f"{base_filename}_run{run_number}.npy"):
            run_number += 1
        return f"{base_filename}_run{run_number}.npy"

    def get_available_filename(self, params, base_filename):
        new_filename = f"{base_filename}_run{params['ssi_run_time']}.npy"
        return new_filename

    def create_train_sample_data_loader(self, params):
        print(
            "Resample at scale: ",
            params["train_sample_ratio"],
            params["spa_enc_type"],
            "Using the sammpling method: ",
            params["train_sample_method"],
        )
        if (
            params["train_sample_ratio"] < 1.0
            and params["train_sample_ratio"] > 0
            and params["spa_enc_type"] not in self.spa_enc_baseline_list
            and params["train_sample_method"] != "ssi-sample"
        ):
            # we need to sample the training dataset for supervised learning
            train_sample_idx_file = dtul.get_sample_idx_file_path(
                dataset=params["dataset"],
                meta_type=params["meta_type"],
                data_split="train",
                sample_ratio=params["train_sample_ratio"],
                sample_method=params["train_sample_method"],
            )

            # params["train_sample_idx_file"] = self.get_next_available_filename(train_sample_idx_file[:-4])
            params["train_sample_idx_file"] = self.get_available_filename(
                params, train_sample_idx_file[:-4]
            )
            print("Sample idx file: ", params["train_sample_idx_file"])
            sample_type, sample_seed = params["train_sample_method"].split("-")
            if sample_seed == "fix" and os.path.exists(train_sample_idx_file):
                # sample_seed == "fix" and if we have sampled idxs, just use the existing one
                self.train_sample_idxs = np.load(
                    train_sample_idx_file, allow_pickle=True
                )
            else:
                if sample_type == "stratified":
                    # if not we generate one and save it
                    self.train_sample_idxs, _ = dtul.get_classes_sample_idxs(
                        classes=self.op["train_classes"],
                        sample_ratio=params["train_sample_ratio"],
                    )
                elif sample_type == "random":
                    num_sample = self.op["train_classes"].shape[0]
                    self.train_sample_idxs = np.sort(
                        np.random.choice(
                            list(range(num_sample)),
                            size=int(num_sample * params["train_sample_ratio"]),
                            replace=False,
                        )
                    )
                else:
                    raise Exception(
                        f'Unknown train_sample_method: {params["train_sample_method"]}'
                    )

                self.train_sample_idxs.dump(params["train_sample_idx_file"])

            # self.train_sample_idxs_tensor = torch.from_numpy(self.train_sample_idxs).to(params['device'])
            (
                self.train_sample_dataset,
                self.train_sample_loader,
                self.train_sample_labels,
                self.train_sample_loc_feats,
                self.train_sample_users,
                self.train_sample_feats,
            ) = self.create_dataset_data_loader(
                params,
                data_flag="train",
                classes=self.op["train_classes"][self.train_sample_idxs],
                locs=self.op["train_locs"][self.train_sample_idxs],
                dates=self.op["train_dates"][self.train_sample_idxs],
                users=self.train_users_np[self.train_sample_idxs],
                cnn_features=self.op["train_feats"][self.train_sample_idxs]
                if self.op["train_feats"] is not None
                else None,
            )
        elif (
            params["train_sample_ratio"] < 1.0
            and params["train_sample_ratio"] > 0
            and params["train_sample_method"] == "ssi-sample"
        ):
            feature_mapping = {"pred": "train_preds", "feat": "train_feats"}
            train_sample_idx_file = dtul.get_ssi_sample_idx_file_path(
                params=params,
                dataset=params["dataset"],
                meta_type=params["meta_type"],
                data_split="train",
                sample_ratio=params["train_sample_ratio"],
                sample_method=params["train_sample_method"],
            )
            params["train_sample_idx_file"] = train_sample_idx_file

            if os.path.exists(train_sample_idx_file):
                self.train_sample_idxs = np.load(
                    train_sample_idx_file, allow_pickle=True
                )
            else:
                feats = self.op[feature_mapping[params["ssi_sample_feat_type"]]]
                locs = self.op["train_locs"]
                feats = torch.from_numpy(feats).to(params["device"])
                locs = torch.from_numpy(locs).to(params["device"])
                self.train_sample_idxs = ssi_sample(
                    features=feats,
                    locations=locs,
                    sample_rate=params["train_sample_ratio"],
                    k=params["ssi_sample_k"],
                    radius=params["ssi_sample_radius"],
                    n_bg=params["ssi_sample_n_bg"],
                    bucket_size=params["ssi_sample_bucket_size"],
                    inverse=False,
                )
                self.train_sample_idxs.dump(train_sample_idx_file)

            # self.train_sample_idxs_tensor = torch.from_numpy(self.train_sample_idxs).to(params['device'])
            (
                self.train_sample_dataset,
                self.train_sample_loader,
                self.train_sample_labels,
                self.train_sample_loc_feats,
                self.train_sample_users,
                self.train_sample_feats,
            ) = self.create_dataset_data_loader(
                params,
                data_flag="train",
                classes=self.op["train_classes"][self.train_sample_idxs],
                locs=self.op["train_locs"][self.train_sample_idxs],
                dates=self.op["train_dates"][self.train_sample_idxs],
                users=self.train_users_np[self.train_sample_idxs],
                cnn_features=self.op["train_feats"][self.train_sample_idxs]
                if self.op["train_feats"] is not None
                else None,
            )
            final_df = pd.DataFrame(
                {
                    "train_classes": self.op["train_classes"][self.train_sample_idxs],
                    "train_locs": self.op["train_locs"][self.train_sample_idxs],
                    "train_dates": self.op["train_dates"][self.train_sample_idxs],
                    "train_users": self.train_users_np[self.train_sample_idxs],
                }
            )
            final_df.to_csv("combined_data.csv", index=False)
        else:
            (
                self.train_sample_dataset,
                self.train_sample_loader,
                self.train_sample_labels,
                self.train_sample_loc_feats,
                self.train_sample_users,
                self.train_sample_feats,
            ) = None, None, None, None, None, None

    def create_train_val_data_loader(self, params):
        if params["spa_enc_type"] not in self.spa_enc_baseline_list:
            if params["dataset"] not in params["regress_dataset"]:
                (
                    self.train_dataset,
                    self.train_loader,
                    self.train_labels,
                    self.train_loc_feats,
                    self.train_users,
                    self.train_feats,
                ) = self.create_dataset_data_loader(
                    params,
                    data_flag="train",
                    classes=self.op["train_classes"],
                    locs=self.op["train_locs"],
                    dates=self.op["train_dates"],
                    users=self.train_users_np,
                    cnn_features=self.op["train_feats"],
                )

                (
                    self.val_dataset,
                    self.val_loader,
                    self.val_labels,
                    self.val_loc_feats,
                    self.val_users,
                    self.val_feats,
                ) = self.create_dataset_data_loader(
                    params,
                    data_flag="val",
                    classes=self.op["val_classes"],
                    locs=self.op["val_locs"],
                    dates=self.op["val_dates"],
                    users=self.op["val_users"],
                    cnn_features=self.op["val_feats"],
                )
            else:
                (
                    self.train_dataset,
                    self.train_loader,
                    self.train_labels,
                    self.train_loc_feats,
                    self.train_feats,
                ) = self.create_dataset_data_loader(
                    params,
                    data_flag="train",
                    labels=self.op["train_labels"],
                    locs=self.op["train_locs"],
                    cnn_features=self.op["train_feats"],
                )

                (
                    self.val_dataset,
                    self.val_loader,
                    self.val_labels,
                    self.val_loc_feats,
                    self.val_feats,
                ) = self.create_dataset_data_loader(
                    params,
                    data_flag="val",
                    labels=self.op["val_labels"],
                    locs=self.op["val_locs"],
                    cnn_features=self.op["val_feats"],
                )

        else:
            (
                self.train_dataset,
                self.train_loader,
                self.train_labels,
                self.train_loc_feats,
                self.train_users,
                self.train_feats,
            ) = None, None, None, None, None, None

            (
                self.val_dataset,
                self.val_loader,
                self.val_labels,
                self.val_loc_feats,
                self.val_users,
                self.val_feats,
            ) = None, None, None, None, None, None

    def create_regress_model(self):
        # Sustainbench regression task
        if self.params["dataset"].startswith("sustainbench"):
            img_enc_model = models.SustainBenchRegressNet(
                params=self.params,
                train_dataset=self.op["train_feats"],
                device=self.params["device"],
                loc_enc=self.loc_enc_model,
            ).to(self.params["device"])
            return img_enc_model

        elif self.params["dataset"].startswith("mosaiks"):
            print
            return models.MosaiksRegressNet(
                params=self.params,
                input_dim=self.params["embed_dim_before_regress"],
                dropout_p=self.params["mosaiks_net_dropout"],
                hidden_dim=self.params["mosaiks_hidden_dim"],
                loc_enc=self.loc_enc_model,
                device=self.params["device"],
            ).to(self.params["device"])

        return None

    def create_loc_model(self):
        if self.params["spa_enc_type"] not in self.spa_enc_baseline_list:
            # create model
            self.params["num_loc_feats"] = self.train_loc_feats.shape[1]
            self.params["num_feats"] = self.params["num_loc_feats"]

            # classification
            if self.params["dataset"] not in self.params["regress_dataset"]:
                loc_enc = ut.get_loc_model(
                    train_locs=self.op["train_locs"],
                    params=self.params,
                    spa_enc_type=self.params["spa_enc_type"],
                    num_inputs=self.params["num_loc_feats"],
                    num_classes=self.params["num_classes"],
                    num_filts=self.params["num_filts"],
                    num_users=self.params["num_users"],
                    device=self.params["device"],
                )
            # regression
            elif self.params["load_cnn_features_train"]:
                loc_enc = ut.get_loc_model(
                    train_locs=self.op["train_locs"],
                    params=self.params,
                    spa_enc_type=self.params["spa_enc_type"],
                    num_inputs=self.params["num_loc_feats"],
                    num_classes=self.params[
                        "embed_dim_before_regress"
                    ],  # for regression, the loc encoder returns a params["embed_dim_before_regress"]-dim location embedding
                    num_filts=self.params["num_filts"],
                    num_users=None,
                    device=self.params["device"],
                )
            else:
                raise ValueError(
                    "For regression tasks, 'load_cnn_features_train' is required."
                )

            unsuper_loss = self.params["unsuper_loss"]

            if unsuper_loss == "none":
                return loc_enc
            elif unsuper_loss in [
                "l2regress",
                "imgcontloss",
                "imgcontlossnolocneg",
                "imgcontlosssimcse",
                "contsoftmax",
                "contsoftmaxsym",
            ]:
                assert self.train_feats is not None
                self.params["cnn_feat_dim"] = self.train_feats.shape[-1]

                model = models.LocationImageEncoder(
                    loc_enc=loc_enc,
                    train_loss=self.params["train_loss"],
                    unsuper_loss=unsuper_loss,
                    cnn_feat_dim=self.params["cnn_feat_dim"],
                    spa_enc_type=self.params["spa_enc_type"],
                ).to(self.params["device"])
                return model
            else:
                raise Exception(f"Unknown unsuper_loss={unsuper_loss}")
        else:
            model = None
        return model

    def set_up_grid_predictor(self):
        # set up grid to make dense prediction across world
        self.gp = grid.GridPredictor(self.mask, self.params)

    def plot_groundtruth(self):
        # plot ground truth
        plt.close("all")
        plot_gt_locations(
            self.params,
            self.mask,
            self.op["train_classes"],
            self.op["class_of_interest"],
            self.op["classes"],
            self.op["train_locs"],
            self.op["train_dates"],
            self.op_dir,
        )

    def run_unsuper_train(self):
        if (
            self.params["unsuper_loss"] != "none"
            and self.params["num_epochs_unsuper"] > 0
        ):
            # adjust the learning rate
            # we readjust the lr as the initial lr during supervised training
            for param_group in self.optimizer.param_groups:
                param_group["lr"] = self.params["unsuper_lr"] * (
                    self.params["lr_decay"] ** self.epoch
                )

            for epoch in range(0, self.params["num_epochs_unsuper"]):
                self.logger.info("\nUnsupervised Training Epoch\t{}".format(epoch))
                unsupervise_train(
                    model=self.loc_enc_model,
                    data_loader=self.train_loader,
                    optimizer=self.optimizer,
                    epoch=epoch,
                    params=self.params,
                    logger=self.logger,
                    neg_rand_type=self.params["neg_rand_type"],
                )

                if (
                    epoch % self.params["unsuper_save_frequency"] == 0
                    and epoch != 0
                    and self.params["do_epoch_save"]
                ):
                    self.save_model(unsuper_model=True, cur_epoch=epoch)

            self.save_model(unsuper_model=True)

    def run_super_train(self):
        if self.params["unsuper_loss"] != "none":
            # adjust the learning rate
            # we readjust the lr as the initial lr during supervised training
            for param_group in self.optimizer.param_groups:
                param_group["lr"] = self.params["lr"] * (
                    self.params["lr_decay"] ** self.epoch
                )

        if (
            self.params["train_sample_ratio"] < 1.0
            and self.params["train_sample_ratio"] > 0
            and self.train_sample_loader is not None
        ):
            train_loader = self.train_sample_loader
        else:
            train_loader = self.train_loader

        self.logger.info(f"""
############## SSI Parameters #################
Train Sample Ratio: {self.params['train_sample_ratio']}
Run Time: {self.params['ssi_run_time']}
SSI Loop: {self.params['ssi_loop']}
###############################################
""")

        # main train loop
        for epoch in range(self.epoch, self.epoch + self.params["num_epochs"]):
            self.logger.info("\nEpoch\t{}".format(epoch))
            # classification
            if self.regress_enc_model is None:
                train(
                    model=self.loc_enc_model,
                    data_loader=train_loader,
                    optimizer=self.optimizer,
                    epoch=epoch,
                    params=self.params,
                    logger=self.logger,
                    neg_rand_type=self.params["neg_rand_type"],
                )
                test(
                    model=self.loc_enc_model,
                    data_loader=self.val_loader,
                    params=self.params,
                    logger=self.logger,
                )

                if (
                    epoch % self.params["eval_frequency"] == 0
                    and epoch != 0
                    and self.params["dataset"] not in self.params["regress_dataset"]
                ):
                    # self.run_eval_spa_enc_only(
                    #     eval_flag_str=f"LocEnc (Epoch {epoch})", load_model=False
                    # )
                    self.run_eval_final(eval_flag_str=f"(Epoch {epoch})")
                    # if self.params["do_epoch_save"]:
                    #     self.save_model(unsuper_model = False, cur_epoch = epoch)
            else:
                train(
                    model=self.regress_enc_model,
                    data_loader=train_loader,
                    optimizer=self.optimizer,
                    epoch=epoch,
                    params=self.params,
                    logger=self.logger,
                    neg_rand_type=self.params["neg_rand_type"],
                )
                test(
                    model=self.regress_enc_model,
                    data_loader=self.val_loader,
                    params=self.params,
                    logger=self.logger,
                )

                if (
                    epoch % self.params["eval_frequency"] == 0
                    and epoch != 0
                    and self.params["dataset"] not in self.params["regress_dataset"]
                ):
                    self.run_eval_spa_enc_only(
                        eval_flag_str=f"LocEnc (Epoch {epoch})", load_model=False
                    )
                    self.run_eval_final(eval_flag_str=f"(Epoch {epoch})")
                    # if self.params["do_epoch_save"]:
                    #     self.save_model(unsuper_model = False, cur_epoch = epoch)

            self.epoch += 1

        self.save_model(unsuper_model=False)

    def run_train(self):
        if self.params["load_unsuper_model"]:
            self.load_model(unsuper_model=True)

        if self.params["do_unsuper_train"]:
            self.run_unsuper_train()

        if self.params["load_super_model"]:
            self.load_model(unsuper_model=False)

        if self.params["do_super_train"]:
            self.run_super_train()

        self.save_model()

    def plot_time_preidction(self):
        if self.params["use_date_feats"]:
            self.logger.info("\nGenerating predictions for each month of the year.")
            if not os.path.isdir(self.op_dir + "time/"):
                os.makedirs(self.op_dir + "time/")
            for ii, tm in enumerate(np.linspace(0, 1, 13)):
                grid_pred = self.gp.dense_prediction(
                    self.loc_enc_model, self.op["class_of_interest"], tm
                )
                op_file_name = (
                    self.op_dir
                    + "time/"
                    + str(self.op["class_of_interest"]).zfill(4)
                    + "_"
                    + str(ii)
                    + ".jpg"
                )
                plt.imsave(op_file_name, 1 - grid_pred, cmap="afmhot", vmin=0, vmax=1)

    def load_model(self, unsuper_model=False, cur_epoch=None):
        if unsuper_model:
            model_file_name = self.params["unsuper_model_file_name"]
        else:
            model_file_name = self.params["model_file_name"]

        if cur_epoch is not None:
            model_file_name = model_file_name.replace(
                ".pth.tar", f"-Epoch-{cur_epoch}.pth.tar"
            )

        if model_file_name is not None:
            if os.path.exists(model_file_name):
                self.logger.info("\nOnly {}".format(self.params["spa_enc_type"]))
                self.logger.info(" Model :\t" + os.path.basename(model_file_name))

                net_params = torch.load(
                    model_file_name, map_location=torch.device(self.params["device"])
                )
                # params = net_params['params']
                # for key in params:
                #     self.params[key] = params[key]
                print("Successfully loaded model: ", model_file_name)

                self.epoch = net_params["epoch"]
                self.loc_enc_model.load_state_dict(net_params["state_dict"])
                self.optimizer.load_state_dict(net_params["optimizer"])
            else:
                self.logger.info(
                    f"Cannot load model since it not exist - {model_file_name}"
                )
                raise FileNotFoundError(
                    f"Model file does not exist - {model_file_name}"
                )
        else:
            if unsuper_model:
                self.logger.info("Cannot load unsupervised model!")
                raise ValueError("Cannot load unsupervised model!")
            else:
                self.logger.info("Cannot load model!")
                raise ValueError("Cannot load model!")

    def save_model(self, unsuper_model=False, cur_epoch=None):
        if unsuper_model:
            model_file_name = self.params["unsuper_model_file_name"]
        else:
            model_file_name = self.params["model_file_name"]

        if cur_epoch is not None:
            model_file_name = model_file_name.replace(
                ".pth.tar", f"-Epoch-{cur_epoch}.pth.tar"
            )

        if model_file_name is not None:
            # save trained model
            self.logger.info("Saving output model to " + model_file_name)
            op_state = {
                "epoch": self.epoch + 1,
                "state_dict": self.loc_enc_model.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "params": self.params,
            }
            torch.save(op_state, model_file_name)
        else:
            if unsuper_model:
                self.logger.info("Cannot save unsupervised model!")
            else:
                self.logger.info("Cannot save model!")

    def load_baseline_hyperparameter(self):
        # these hyper parameters have been cross validated for the baseline methods
        return get_cross_val_hyper_params(eval_params=self.params)

    def run_est_eval_batch(self):
        """
        This is a batch evaluation during training time,
        we just use the val/test dataset after removing invalid samples
        op = dt.load_dataset(params, eval_split = params['eval_split'],
                            train_remove_invalid = True,
                            eval_remove_invalid = True)
        This is just an estimate of the evluation metric
        """

        spa_enc_algs = set(ut.get_spa_enc_list() + ["wrap"])

        spa_enc_type = self.params["spa_enc_type"]
        assert spa_enc_type in spa_enc_algs

        nn_model_path = self.params["model_file_name"]

        self.logger.info("\n{}".format(spa_enc_type))
        self.logger.info(" Model :\t" + os.path.basename(nn_model_path))
        self.logger.info(
            f"""Evaluation on {self.params["eval_split"]} with invalid sample removed"""
        )

        net_params = torch.load(nn_model_path)
        self.params = net_params["params"]

        # construct features
        # val_feats_net: shape [batch_size, 2], torch.tensor
        val_feats_net = self.val_loc_feats

        self.loc_enc_model.load_state_dict(net_params["state_dict"])
        self.loc_enc_model.eval()
        val_preds_final = compute_acc_batch(
            val_preds=self.val_preds,
            val_classes=self.op["val_classes"],
            val_split=self.op["eval_split"],
            val_feats=self.val_loc_feats,
            train_classes=None,
            train_feats=None,
            prior_type=spa_enc_type,
            prior=self.loc_enc_model,
            batch_size=self.params["batch_size"],
            logger=self.logger,
            eval_flag_str="Estimate\t",
        )

        # if save_eval:
        #     pred_no_prior = self.run_eval_baseline(spa_enc_type = 'no_prior')
        #     self.save_eval(val_preds_final = val_preds_final, val_pred_no_prior = pred_no_prior)

    def save_eval(self, val_preds_final, val_pred_no_prior):
        np.savez(
            "model_preds",
            val_classes=self.op["val_classes"],
            pred_geo_net=val_preds_final,
            pred_no_prior=val_pred_no_prior,
            dataset=self.params["dataset"],
            split=self.params["eval_split"],
            # model_type=self.params['model_type']
        )

    def check_spa_enc_type_list(self, params, spa_enc_type_list):
        if "no_prior" not in spa_enc_type_list:
            spa_enc_type_list += ["no_prior"]
        spa_enc_type = params["spa_enc_type"]
        if spa_enc_type not in spa_enc_type_list:
            spa_enc_type_list += [spa_enc_type]
        return spa_enc_type_list

    def edit_eval_flag_str(self, eval_flag_str):
        if self.params["cnn_pred_type"] == "full":
            eval_flag_str += ""
        elif self.params["cnn_pred_type"] == "fewshot":
            eval_flag_str += f" fewshot-ratio{self.params['train_sample_ratio']:.3f} "
        else:
            raise Exception(f"Unrecognized cnn_pred_type -> {params['cnn_pred_type']}")
        return eval_flag_str

    def run_eval_final(
        self,
        spa_enc_type_list=["no_prior"],
        save_eval=False,
        hyper_params=None,
        eval_flag_str="",
    ):
        """
        This is the real evaluation metric,
        since we need to load dataset again which allows invalid sample in val/test
        """
        if self.params["dataset"] not in self.params["regress_dataset"]:
            spa_enc_type_list = self.check_spa_enc_type_list(
                self.params, spa_enc_type_list
            )

            if self.val_op is None or "tang_et_al" in spa_enc_type_list:
                # load the dataset for final evaluation if:
                #  1. we have not preload it before
                #  2. the previous val_op does not load val cnn_features while we have 'tang_et_al' in spa_enc_type_list
                self.load_val_dataset(self.params, spa_enc_type_list)
            op = self.val_op

            if hyper_params is None:
                self.hyper_params = self.load_baseline_hyperparameter()
            else:
                self.hyper_params = hyper_params

            eval_flag_str = self.edit_eval_flag_str(eval_flag_str)
            #
            # no prior
            #
            if "no_prior" in spa_enc_type_list:
                self.logger.info("\nNo prior")
                pred_no_prior = compute_acc_batch(
                    params=self.params,
                    val_preds=op["val_preds"],
                    val_classes=op["val_classes"],
                    val_split=op["val_split"],
                    val_feats=None,
                    train_classes=None,
                    train_feats=None,
                    prior_type="no_prior",
                    prior=None,
                    hyper_params=None,
                    batch_size=1024,
                    logger=self.logger,
                    eval_flag_str=eval_flag_str,
                )

            #
            # overall training frequency prior
            #
            if "train_freq" in spa_enc_type_list:
                self.logger.info("\nTrain frequency prior")
                # weight the eval predictions by the overall frequency of each class at train time
                cls_id, cls_cnt = np.unique(
                    self.op["train_classes"], return_counts=True
                )
                train_prior = np.ones(self.params["num_classes"])
                train_prior[cls_id] += cls_cnt
                train_prior /= train_prior.sum()
                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        prior_type="train_freq",
                        prior=train_prior,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        prior_type="train_freq",
                        prior=train_prior,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )

            #
            # Tang et al ICCV 2015, Improving Image Classification with Location Context
            #
            if "tang_et_al" in spa_enc_type_list:
                # path to trained models
                meta_str = ""
                if self.params["dataset"] in ["birdsnap", "nabirds"]:
                    meta_str = "_" + self.params["meta_type"]

                nn_model_path_tang = "{}/bl_tang_{}{}_gps.pth.tar".format(
                    self.params["model_dir"], self.params["dataset"], meta_str
                )

                self.logger.info("\nTang et al. prior")
                self.logger.info(
                    "  using model :\t" + os.path.basename(nn_model_path_tang)
                )
                net_params = torch.load(nn_model_path_tang)
                params = net_params["params"]

                # construct features
                val_feats_tang = {}
                val_feats_tang["val_locs"] = ut.convert_loc_to_tensor(op["val_locs"])
                val_feats_tang["val_feats"] = torch.from_numpy(op["val_feats"])
                assert params["loc_encoding"] == "gps"

                model = models.TangNet(
                    params["loc_feat_size"],
                    params["net_feats_dim"],
                    params["embedding_dim"],
                    params["num_classes"],
                    params["use_loc"],
                )
                model.load_state_dict(net_params["state_dict"])
                model.eval()

                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        prior_type="train_freq",
                        prior=train_prior,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_feats_tang,
                        prior_type="tang_et_al",
                        prior=model,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                del val_feats_tang  # save memory

            #
            # discretized grid prior
            #
            if "grid" in spa_enc_type_list:
                self.logger.info("\nDiscrete grid prior")
                gp = bl.GridPrior(
                    self.op["train_locs"],
                    self.op["train_classes"],
                    self.params["num_classes"],
                    self.hyper_params,
                )
                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=op["val_locs"],
                        prior_type="grid",
                        prior=gp,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=op["val_locs"],
                        prior_type="grid",
                        prior=gp,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )

            #
            # setup look up tree for NN lookup based methods
            #
            if ("nn_knn" in spa_enc_type_list) or ("nn_dist" in spa_enc_type_list):
                if self.hyper_params["dist_type"] == "haversine":
                    nn_tree = BallTree(
                        np.deg2rad(self.op["train_locs"])[:, ::-1], metric="haversine"
                    )
                    val_locs_n = np.deg2rad(op["val_locs"])
                else:
                    nn_tree = BallTree(
                        self.op["train_locs"][:, ::-1], metric="euclidean"
                    )
                    val_locs_n = op["val_locs"]

            #
            # nearest neighbor prior - based on KNN
            #
            if "nn_knn" in spa_enc_type_list:
                self.logger.info("\nNearest neighbor KNN prior")
                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_n,
                        train_classes=self.op["train_classes"],
                        prior_type="nn_knn",
                        prior=nn_tree,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_n,
                        train_classes=self.op["train_classes"],
                        prior_type="nn_knn",
                        prior=nn_tree,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )

            #
            # nearest neighbor prior - based on distance
            #
            if "nn_dist" in spa_enc_type_list:
                self.logger.info("\nNearest neighbor distance prior")
                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_n,
                        train_classes=self.op["train_classes"],
                        prior_type="nn_dist",
                        prior=nn_tree,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_n,
                        train_classes=self.op["train_classes"],
                        prior_type="nn_dist",
                        prior=nn_tree,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )

            #
            # kernel density estimate e.g. BirdSnap CVPR 2014
            #
            if "kde" in spa_enc_type_list:
                self.logger.info("\nKernel density estimate prior")
                kde_params = {}
                train_classes_kde, train_locs_kde, kde_params["counts"] = (
                    bl.create_kde_grid(
                        self.op["train_classes"],
                        self.op["train_locs"],
                        self.hyper_params,
                    )
                )
                if self.hyper_params["kde_dist_type"] == "haversine":
                    train_locs_kde = np.deg2rad(train_locs_kde)
                    val_locs_kde = np.deg2rad(op["val_locs"])
                    kde_params["nn_tree_kde"] = BallTree(
                        train_locs_kde[:, ::-1], metric="haversine"
                    )
                else:
                    val_locs_kde = op["val_locs"]
                    kde_params["nn_tree_kde"] = BallTree(
                        train_locs_kde[:, ::-1], metric="euclidean"
                    )

                if self.params["save_results"]:
                    compute_acc_predict_result(
                        params=self.params,
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_kde,
                        train_classes=train_classes_kde,
                        train_feats=train_locs_kde,
                        prior_type="kde",
                        prior=kde_params,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )
                else:
                    compute_acc(
                        val_preds=op["val_preds"],
                        val_classes=op["val_classes"],
                        val_split=op["val_split"],
                        val_feats=val_locs_kde,
                        train_classes=train_classes_kde,
                        train_feats=train_locs_kde,
                        prior_type="kde",
                        prior=kde_params,
                        hyper_params=self.hyper_params,
                        logger=self.logger,
                        eval_flag_str=eval_flag_str,
                    )

            if self.params["spa_enc_type"] not in self.spa_enc_baseline_list:
                print("With", self.params["spa_enc_type"])
                val_preds_final = self.run_eval_spa_enc_final(
                    op, eval_flag_str=eval_flag_str
                )
                # print the evualtion metric when we only use spa_enc
                # val_preds = self.run_eval_spa_enc_only()
            if save_eval:
                self.save_eval(
                    val_preds_final=val_preds_final, val_pred_no_prior=pred_no_prior
                )
        else:
            compute_regression_acc(
                params=self.params,
                model=self.regress_enc_model,
                val_locs=self.val_loc_feats,
                val_feats=self.val_feats,
                val_labels=self.val_labels,
                # prior_type="train_freq",
                # prior=train_prior,
                logger=self.logger,
            )

    def run_eval_spa_enc_final(self, op, eval_flag_str=""):
        spa_enc_type = self.params["spa_enc_type"]
        spa_enc_algs = set(ut.get_spa_enc_list() + ["wrap"])
        assert spa_enc_type in spa_enc_algs

        # self.load_model()

        # construct features
        # val_loc_feats: shape [batch_size, 2], torch.tensor
        val_loc_feats = ut.generate_model_input_feats(
            spa_enc_type=spa_enc_type,
            locs=op["val_locs"],
            dates=op["val_dates"],
            params=self.params,
            device=self.params["device"],
        )

        self.loc_enc_model.eval()
        if self.params["save_results"]:
            val_preds_final = compute_acc_predict_result(
                params=self.params,
                val_preds=op["val_preds"],
                val_classes=op["val_classes"],
                val_split=op["val_split"],
                val_feats=val_loc_feats,
                prior_type=spa_enc_type,
                prior=self.loc_enc_model,
                logger=self.logger,
                eval_flag_str=eval_flag_str,
            )
        else:
            val_preds_final = compute_acc(
                val_preds=op["val_preds"],
                val_classes=op["val_classes"],
                val_split=op["val_split"],
                val_feats=val_loc_feats,
                prior_type=spa_enc_type,
                prior=self.loc_enc_model,
                logger=self.logger,
                eval_flag_str=eval_flag_str,
            )

        return val_preds_final

    def run_eval_spa_enc_rank_final(self, op, eval_flag_str=""):
        spa_enc_type = self.params["spa_enc_type"]
        spa_enc_algs = set(ut.get_spa_enc_list() + ["wrap"])
        assert spa_enc_type in spa_enc_algs

        # self.load_model()

        # construct features
        # val_loc_feats: shape [batch_size, 2], torch.tensor
        val_loc_feats = ut.generate_model_input_feats(
            spa_enc_type=spa_enc_type,
            locs=op["val_locs"],
            dates=op["val_dates"],
            params=self.params,
            device=self.params["device"],
        )

        self.loc_enc_model.eval()
        val_preds_final, val_ranks = compute_acc_and_rank(
            val_preds=op["val_preds"],
            val_classes=op["val_classes"],
            val_split=op["val_split"],
            val_feats=val_loc_feats,
            prior_type=spa_enc_type,
            prior=self.loc_enc_model,
            logger=self.logger,
            eval_flag_str=eval_flag_str,
        )

        return val_preds_final, val_ranks

    def run_eval_spa_enc_only(self, eval_flag_str="LocEnc ", load_model=True):
        # get the evaluation metric when we just use spa_enc to do the prediction without image prediction

        op = self.op
        spa_enc_type = self.params["spa_enc_type"]
        spa_enc_algs = set(
            ut.get_spa_enc_list() + ["wrap"] + self.spa_enc_baseline_list
        )
        assert spa_enc_type in spa_enc_algs

        if self.params["dataset"] not in self.params["regress_dataset"]:
            if load_model:
                self.load_model()

            # construct features
            # val_loc_feats: shape [batch_size, 2], torch.tensor
            val_loc_feats = ut.generate_model_input_feats(
                spa_enc_type=spa_enc_type,
                locs=op["val_locs"],
                dates=op["val_dates"],
                params=self.params,
                device=self.params["device"],
            )

            self.loc_enc_model.eval()

            val_preds = compute_acc_batch(
                params=self.params,
                val_preds=None,
                val_classes=op["val_classes"],
                val_split=op["val_split"],
                val_feats=val_loc_feats,
                train_classes=None,
                train_feats=None,
                prior_type=spa_enc_type,
                prior=self.loc_enc_model,
                hyper_params=None,
                batch_size=1024,
                logger=self.logger,
                eval_flag_str=eval_flag_str,
            )

            return val_preds
