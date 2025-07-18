import librosa as lb
import numpy as np
from pathlib import Path
import yaml
import time
from tqdm import tqdm
import logging
import importlib
import json

logger = logging.getLogger("bacpipe")


class Loader:
    def __init__(
        self,
        audio_dir,
        check_if_combination_exists=True,
        model_name=None,
        dim_reduction_model=False,
        testing=False,
        **kwargs,
    ):
        self.model_name = model_name
        self.audio_dir = Path(audio_dir)
        self.dim_reduction_model = dim_reduction_model
        self.testing = testing

        self.initialize_path_structure(testing=testing)

        self.check_if_combination_exists = check_if_combination_exists
        if self.dim_reduction_model:
            self.embed_suffix = ".json"
        else:
            self.embed_suffix = ".npy"

        start = time.time()
        self.check_embeds_already_exist()
        logger.debug(
            f"Checking if embeddings already exist took {time.time()-start:.2f}s."
        )

        if self.combination_already_exists or self.dim_reduction_model:
            self.get_embeddings()
        else:
            self._get_audio_paths()
            self._init_metadata_dict()

        if not self.combination_already_exists:
            self.embed_dir.mkdir(exist_ok=True, parents=True)
        else:
            logger.debug(
                "Combination of {} and {} already "
                "exists -> using saved embeddings in {}".format(
                    self.model_name, Path(self.audio_dir).stem, str(self.embed_dir)
                )
            )

    def initialize_path_structure(self, testing=False):
        with open("bacpipe/settings.yaml", "r") as f:
            self.config = yaml.load(f, Loader=yaml.CLoader)

        if testing:
            self.config["main_results_dir"] = "bacpipe/tests/results_files"

        for key, val in self.config.items():
            if key == "main_results_dir":
                continue
            if key in ["embed_parent_dir", "dim_reduc_parent_dir", "evaluations_dir"]:
                val = (
                    Path(self.config["main_results_dir"])
                    .joinpath(self.audio_dir.stem)
                    .joinpath(val)
                )
                val.mkdir(exist_ok=True, parents=True)
            setattr(self, key, val)

    def check_embeds_already_exist(self):
        self.combination_already_exists = False
        self.dim_reduc_embed_dir = False

        if self.check_if_combination_exists:
            if self.dim_reduction_model:
                existing_embed_dirs = Path(self.dim_reduc_parent_dir).iterdir()
            else:
                existing_embed_dirs = Path(self.embed_parent_dir).iterdir()
            existing_embed_dirs = list(existing_embed_dirs)
            if isinstance(self.check_if_combination_exists, str):
                existing_embed_dirs = [
                    existing_embed_dirs[0].parent.joinpath(
                        self.check_if_combination_exists
                    )
                ]
            existing_embed_dirs.sort()
            self._find_existing_embed_dir(existing_embed_dirs)

    def _find_existing_embed_dir(self, existing_embed_dirs):
        for d in existing_embed_dirs[::-1]:

            if self.model_name in d.stem and Path(self.audio_dir).stem in d.parts[-1]:
                if list(d.glob("*yml")) == []:
                    try:
                        d.rmdir()
                        continue
                    except OSError:
                        print(
                            f"Directory {d} is not empty. ",
                            "Please remove it manually.",
                        )
                        continue
                with open(d.joinpath("metadata.yml"), "r") as f:
                    mdata = yaml.load(f, Loader=yaml.CLoader)
                    if not self.model_name == mdata["model_name"]:
                        continue

                if self.dim_reduction_model:
                    if self.dim_reduction_model in d.stem:
                        self.combination_already_exists = True
                        print(
                            "\n### Embeddings already exist. "
                            f"Using embeddings in {str(d)} ###"
                        )
                        self.embed_dir = d
                        break
                    else:
                        return d
                else:
                    try:
                        num_files = len(
                            [f for f in list(d.rglob(f"*{self.embed_suffix}"))]
                        )
                        num_audio_files = len(self._get_audio_files())
                    except AssertionError as e:
                        self._get_metadata_dict(d)
                        self.combination_already_exists = True
                        print(
                            f"Error: {e}. "
                            "Will proceed without veryfying if the number of embeddings "
                            "is the same as the number of audio files."
                        )
                        print(
                            "\n### Embeddings already exist. "
                            f"Using embeddings in {self.metadata_dict['embed_dir']} ###"
                        )
                        break

                    if num_audio_files == num_files:
                        self.combination_already_exists = True
                        self._get_metadata_dict(d)
                        print(
                            "\n### Embeddings already exist. "
                            f"Using embeddings in {self.metadata_dict['embed_dir']} ###"
                        )
                        break

    def _get_audio_paths(self):
        self.files = self._get_audio_files()
        self.files.sort()
        if False:
            self._get_annotation_files()

        self.embed_dir = Path(self.embed_parent_dir).joinpath(self.get_timestamp_dir())

    def _get_annotation_files(self):
        all_annotation_files = list(self.audio_dir.rglob("*.csv"))
        audio_stems = [file.stem for file in self.files]
        self.annot_files = [
            file for file in all_annotation_files if file.stem in audio_stems
        ]

    def _get_audio_files(self):
        files_list = []
        [
            [files_list.append(ll) for ll in self.audio_dir.rglob(f"*{string}")]
            for string in self.config["audio_suffixes"]
        ]
        files_list = np.unique(files_list).tolist()
        assert len(files_list) > 0, "No audio files found in audio_dir."
        return files_list

    def _init_metadata_dict(self):
        self.metadata_dict = {
            "model_name": self.model_name,
            "audio_dir": str(self.audio_dir),
            "embed_dir": str(self.embed_dir),
            "files": {
                "audio_files": [],
                "file_lengths (s)": [],
                "nr_embeds_per_file": [],
            },
        }

    def _get_metadata_dict(self, folder):
        with open(folder.joinpath("metadata.yml"), "r") as f:
            self.metadata_dict = yaml.load(f, Loader=yaml.CLoader)
        for key, val in self.metadata_dict.items():
            if isinstance(val, str):
                if not Path(val).is_dir():
                    if key == "embed_dir":
                        val = folder.parent.joinpath(Path(val).stem)
                    elif key == "audio_dir":
                        print(
                            "The audio files are no longer where they used to be "
                            "during the previous run. This might cause a problem."
                        )
                setattr(self, key, Path(val))
        if self.dim_reduction_model:
            self.dim_reduc_embed_dir = folder

    def get_embeddings(self):
        embed_dir = self.get_embedding_dir()
        self.files = [f for f in embed_dir.rglob(f"*{self.embed_suffix}")]
        self.files.sort()

        if not self.combination_already_exists:
            self._get_metadata_dict(embed_dir)
            self.metadata_dict["files"].update(
                {"embedding_files": [], "embedding_dimensions": []}
            )
            self.embed_dir = Path(self.dim_reduc_parent_dir).joinpath(
                self.get_timestamp_dir() + f"-{self.model_name}"
            )
        else:
            self.embed_dir = embed_dir

    def get_embedding_dir(self):
        if self.dim_reduction_model:
            if self.combination_already_exists:
                self.embed_parent_dir = Path(self.dim_reduc_parent_dir)
                return self.embed_dir
            else:
                self.embed_parent_dir = Path(self.embed_parent_dir)
                self.embed_suffix = ".npy"
        else:
            return self.embed_dir
        self.audio_dir = Path(self.audio_dir)

        if self.dim_reduc_embed_dir:
            # check if they are compatible
            return self.dim_reduc_embed_dir

        embed_dirs = [
            d
            for d in self.embed_parent_dir.iterdir()
            if self.audio_dir.stem in d.parts[-1] and self.model_name in d.stem
        ]
        # check if timestamp of umap is after timestamp of model embeddings
        embed_dirs.sort()
        return self._find_existing_embed_dir(embed_dirs)

    def get_timestamp_dir(self):
        if self.dim_reduction_model:
            model_name = self.dim_reduction_model
        else:
            model_name = self.model_name
        return time.strftime(
            "%Y-%m-%d_%H-%M___" + model_name + "-" + self.audio_dir.stem,
            time.localtime(),
        )

    def embed_read(self, index, file):
        embeds = np.load(file)
        try:
            rel_file_path = file.relative_to(self.metadata_dict["embed_dir"])
        except ValueError as e:
            logger.debug(
                "\nEmbedding file is not in the same directory structure "
                "as it was when created.\n",
                e,
            )
            rel_file_path = file.relative_to(
                self.embed_parent_dir.joinpath(
                    Path(self.metadata_dict["embed_dir"]).stem
                )
            )
        self.metadata_dict["files"]["embedding_files"].append(str(rel_file_path))
        if len(embeds.shape) == 1:
            embeds = np.expand_dims(embeds, axis=0)
        self.metadata_dict["files"]["embedding_dimensions"].append(embeds.shape)
        return embeds

    def embedding_dict(self):
        d = {}
        for file in self.files:
            if not self.dim_reduction_model:
                embeds = np.load(file)
            else:
                with open(file, "r") as f:
                    embeds = json.load(f)
                embeds = np.array(embeds)
            d[str(file.relative_to(self.embed_dir))] = embeds
        return d

    def write_audio_file_to_metadata(self, index, file, embed, embeddings):
        if index == 0:
            self.metadata_dict["segment_length (samples)"] = embed.model.segment_length
            self.metadata_dict["sample_rate (Hz)"] = embed.model.sr
            self.metadata_dict["embedding_size"] = embeddings.shape[-1]
        rel_file_path = Path(file).relative_to(self.audio_dir)
        self.metadata_dict["files"]["audio_files"].append(str(rel_file_path))
        self.metadata_dict["files"]["file_lengths (s)"].append(embed.file_length)
        self.metadata_dict["files"]["nr_embeds_per_file"].append(embeddings.shape[0])

    def write_metadata_file(self):
        self.metadata_dict["nr_embeds_total"] = sum(
            self.metadata_dict["files"]["nr_embeds_per_file"]
        )
        self.metadata_dict["total_dataset_length (s)"] = sum(
            self.metadata_dict["files"]["file_lengths (s)"]
        )
        with open(str(self.embed_dir.joinpath("metadata.yml")), "w") as f:
            yaml.safe_dump(self.metadata_dict, f)

    def update_files(self):
        if self.dim_reduction_model:
            self.files = [f for f in self.embed_dir.iterdir() if f.suffix == ".json"]
        else:
            self.files = list(self.embed_dir.rglob("*.npy"))


class Embedder:
    def __init__(self, model_name, dim_reduction_model=False, testing=False, **kwargs):
        import yaml

        with open("bacpipe/settings.yaml", "rb") as f:
            self.config = yaml.load(f, Loader=yaml.CLoader)

        if testing:
            self.config["main_results_dir"] = "bacpipe/tests/results_files"

        self.dim_reduction_model = dim_reduction_model
        if dim_reduction_model:
            self.dim_reduction_model = True
            self.model_name = dim_reduction_model
        else:
            self.model_name = model_name
        self._init_model()

    def _init_model(self):
        if self.dim_reduction_model:
            module = importlib.import_module(
                f"bacpipe.embedding_generation_pipelines.dimensionality_reduction.{self.model_name}"
            )
        else:
            module = importlib.import_module(
                f"bacpipe.embedding_generation_pipelines.feature_extractors.{self.model_name}"
            )
        self.model = module.Model()
        self.model.prepare_inference()

    def prepare_audio(self, sample):
        audio = self.model.load_and_resample(sample)
        frames = self.model.window_audio(audio)
        preprocessed_frames = self.model.preprocess(frames)
        self.file_length = len(audio[0]) / self.model.sr
        self.preprocessed_shape = tuple(preprocessed_frames.shape)
        return preprocessed_frames

    def get_embeddings_for_audio(self, sample):
        batched_samples = self.model.init_dataloader(sample)
        embeds = self.model.batch_inference(batched_samples)
        if not isinstance(embeds, np.ndarray):
            try:
                embeds = embeds.numpy()
            except:
                print(type(embeds))
                try:
                    embeds = embeds.detach().numpy()
                except:
                    embeds = embeds.cpu().detach().numpy()
        return embeds

    def get_reduced_dimensionality_embeddings(self, embeds):
        samples = self.model.preprocess(embeds)
        return self.model(samples)

    def get_embeddings_from_model(self, sample):

        start = time.time()
        if self.dim_reduction_model:
            embeds = self.get_reduced_dimensionality_embeddings(sample)
        else:
            sample = self.prepare_audio(sample)
            embeds = self.get_embeddings_for_audio(sample)

        logger.debug(f"{self.model_name} embeddings have shape: {embeds.shape}")
        logger.info(f"{self.model_name} inference took {time.time()-start:.2f}s.")
        return embeds

    def save_embeddings(self, file_idx, fileloader_obj, file, embeds):
        if self.dim_reduction_model:
            file_dest = fileloader_obj.embed_dir.joinpath(
                fileloader_obj.audio_dir.stem + "_" + self.model_name
            )
            file_dest = str(file_dest) + ".json"
            input_len = (
                fileloader_obj.metadata_dict["segment_length (samples)"]
                / fileloader_obj.metadata_dict["sample_rate (Hz)"]
            )
            save_embeddings_dict_with_timestamps(
                file_dest, embeds, input_len, fileloader_obj, file_idx
            )
        else:
            relative_parent_path = (
                Path(file).relative_to(fileloader_obj.audio_dir).parent
            )
            parent_path = fileloader_obj.embed_dir.joinpath(relative_parent_path)
            parent_path.mkdir(exist_ok=True, parents=True)
            file_dest = parent_path.joinpath(file.stem + "_" + self.model_name)
            file_dest = str(file_dest) + ".npy"
            if len(embeds.shape) == 1:
                embeds = np.expand_dims(embeds, axis=0)
            np.save(file_dest, embeds)


def save_embeddings_dict_with_timestamps(
    file_dest, embeds, input_len, loader_obj, f_idx
):

    t_stamps = []
    for num_segments, _ in loader_obj.metadata_dict["files"]["embedding_dimensions"]:
        [t_stamps.append(t) for t in np.arange(0, num_segments * input_len, input_len)]
    d = {
        var: embeds[:, i].tolist() for i, var in zip(range(embeds.shape[1]), ["x", "y"])
    }
    d["timestamp"] = t_stamps

    d["metadata"] = {
        k: (v if isinstance(v, list) else v)
        for (k, v) in loader_obj.metadata_dict["files"].items()
    }
    d["metadata"].update(
        {k: v for (k, v) in loader_obj.metadata_dict.items() if not isinstance(v, dict)}
    )

    import json

    with open(file_dest, "w") as f:
        json.dump(d, f)

    if embeds.shape[-1] > 2:
        embed_dict = {}
        acc_shape = 0
        for shape, file in zip(
            loader_obj.metadata_dict["files"]["embedding_dimensions"],
            loader_obj.files,
        ):
            embed_dict[file.stem] = embeds[acc_shape : acc_shape + shape[0]]
            acc_shape += shape[0]
        np.save(file_dest.replace(".json", f"{embeds.shape[-1]}.npy"), embed_dict)
