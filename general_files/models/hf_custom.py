import torch
from general_files.models.pl_base_model import BasePLModel
from general_files.utils.common_util import Result
import importlib

class ModelNet(BasePLModel):
    def __init__(self, config, tokenizer, as_pipeline=False):
        super(ModelNet, self).__init__(config, tokenizer)
        if ':' in self.config.pretrain_model:
            model_processor_name = self.config.pretrain_model.split(':')[0]
            module_path = config.logger_project + '.modules.' + model_processor_name
            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as r:
                raise ValueError(f"Please add a processor for this model: {model_processor_name}\n"
                                 f"Error module path：{module_path}")
            processor_name = 'CustomModel'
            processor_class = getattr(module, processor_name)
            pretrain_model = self.config.pretrain_model.split(':')[-1]
            self.backbone = processor_class.from_pretrained(pretrain_model,
                                                            cache_dir=self.config.cache_dir,
                                                            hyparam=config,
                                                            tokenizer=tokenizer, )
            self.backbone.resize_token_embeddings(self.tokenizer.vocab_size)
            self.backbone = self.backbone.train()
        else:
            self.model_type = self.model_mode[config.hf_model_type if not as_pipeline else config.pipline_model_type]
            self.backbone = self.init_pretrained_model(self.model_type, as_pipeline)  # 实例化对象

        if self.config.get("use_param_noise", False):
            for name, para in self.backbone.named_parameters():
                self.backbone.state_dict()[name][:] += (torch.rand(
                    para.size()) - 0.5) * config.noise_lambda * torch.std(para)

    def forward(self,
                # batch, seq_len
                input_ids,
                # batch, seq_len
                labels=None,
                # 其他参数或特征
                past_result=None,  # 生成的时候借用此可以省去每次编码
                **other_features  # 如果有其他特征参数，建议加decoder前缀，保持框架一致性
                ):
        result = Result()
        other_features['decoder_stage'] = self.stage
        outputs = self.backbone(input_ids=input_ids,
                                output_hidden_states=True,
                                output_attentions=True,
                                labels=torch.where(labels == self.tokenizer.pad_token_id, -100, labels) if labels is not None else None,
                                attention_mask=input_ids.ne(self.tokenizer.pad_token_id),
                                return_dict=False,
                                use_cache=True,
                                **other_features,
                                )
        lm_logits = outputs[0]

        if len(self.config.get("loss")) < 1:
            raise Exception("请至少选择一个损失函数！")
        loss = 0
        ###############################################
        # 计算交叉熵损失
        ###############################################
        if "lm_loss" in self.config.get("loss") and labels is not None:
            result.add(labels=labels)
            lm_loss = self.CrossEntropyLoss(logits=lm_logits, labels=labels)
            result.add(lm_loss=lm_loss)
            loss += lm_loss

        if self.stage != "test" and (
                loss != loss or isinstance(loss, int)
        ):
            raise Exception("Loss为Nan或无梯度，请先检查数据正确性以及超参中 Loss 是否正确选择！")

        result.add(loss=loss)
        return result


