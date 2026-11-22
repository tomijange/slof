"""Change the image of a container of a workload"""

import logging
from typing import Optional

from pydantic import Field

from oxn.common.errors import OxnException
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams

logger = logging.getLogger(__name__)


class DeploymentImageParams(PodSelectorParams):
    """Params of deployment_image"""

    image: str = Field(min_length=1, examples=["ghcr.io/open-telemetry/demo:2.0.2-recommendation"])
    """The image while the treatment is in place, with registry, repository and tag or digest"""
    container: Optional[str] = Field(default=None, min_length=1)
    """The container whose image changes, by default the first container of the pod template"""


class DeploymentImageTreatment(CompileTimeTreatment[DeploymentImageParams]):
    """
    Will change the image of a container of a workload and back to the image before.
    """

    action = "deployment_image"
    Params = DeploymentImageParams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_before: Optional[str] = None

    def preconditions(self) -> bool:
        super().preconditions()
        return True

    def inject(self) -> None:
        super().inject()
        workload = self.params.workload
        image = self.params.image
        try:
            self.image_before = self.orchestrator.get_image(workload, self.params.container)
            self.orchestrator.set_image(workload, image, self.params.container)
        except OxnException as e:
            self.messages.append(str(e.message))
            return
        logger.info(f"Image of workload with {workload} changed from {self.image_before} to {image}")

    def clean(self) -> None:
        """Change the image back to the one before inject"""
        super().clean()
        if self.image_before is None:
            # inject did not get to read the image, so it did not change it either
            return
        workload = self.params.workload
        try:
            self.orchestrator.set_image(workload, self.image_before, self.params.container)
        except OxnException as e:
            self.messages.append(str(e.message))
            return
        logger.info(f"Image of workload with {workload} changed back to {self.image_before}")
